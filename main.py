#!/usr/bin/env python3
"""agent-core — 逐模块实现 Claude Code 核心架构的教学级 Agent 框架。

钩子系统、三级压缩、工具隔离、技能加载、任务管理、后台执行。

REPL commands: /compact /tasks /team /inbox /hooks
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from queue import Queue

from anthropic import Anthropic
from dotenv import load_dotenv

# ── Bootstrap ────────────────────────────────────────────
load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-6-20250514")

# ── Import modules ────────────────────────────────────────
from src.tools.base import build_tool
from src.tools.registry import ToolRegistry, registry
from src.tools.builtin import run_bash, run_read, run_write, run_edit, run_grep, run_glob
from src.agent.hooks import HookManager, HookInput, HookConfig, hooks
from src.agent.filter_tools import filter_tools_for_agent, get_agent_tool_restriction
from src.agent.loop import agent_loop, run_subagent
from src.skills.loader import SkillLoader
from src.state.store import Store, ToolUseContext
from src.bus.message_bus import MessageBus
from src.bus.scratchpad import Scratchpad
from src.tasks.todo import TodoManager
from src.tasks.task_manager import TaskManager
from src.config.loader import load_config
from src.recovery.error_handler import ErrorRecoveryPipeline
from src.recovery.session import SessionState
from src.bus.mcp_client import MCPClientManager, load_mcp_from_config
from src.agent.intent import IntentClassifier, filter_by_intent, get_tool_names_by_intent
from src.context import ContextOrchestrator, BudgetConfig
from src.context.layers.workspace import WorkspaceLayer
from src.context.layers.file_cache import FileCacheLayer
# M6: Memory OS
from src.memory import MemoryCore
from src.memory.layer import MemoryLayer
from src.memory.collector import MemoryCollector
from src.memory.tools import build_memory_tools
from src.memory.retrieval import RetrievalEngine, RetrievalConfig
# M3: Budget + Compression
from src.context.budget import Budget, BudgetAllocation, BudgetPolicy, BudgetManager
from src.context.compression import (
    OverBudgetRule, CompressionPolicy,
    LLMSummarizer,
    CompressionPipeline, MicroCompactStage, ContextCollapseStage, AutoCompactStage,
    CircuitBreaker,
)
# M4: Context Selection Pipeline
from src.context.selection import (
    InstructionCollector, WorkspaceCollector, SummaryCollector,
    FileCacheCollector, ConversationCollector,
    PriorityRanker, TokenConstraint, BudgetSelectionPolicy,
    SelectionPipeline,
)
# M5: Recovery + Observability
from src.context.recovery import RecoveryEngine
from src.context.observability import AuditLog
# ── Load config ──────────────────────────────────────────
config = load_config(WORKDIR)
TOKEN_THRESHOLD = config.get("token_threshold", 100000)
KEEP_RECENT = config.get("keep_recent_tools", 3)
POLL_INTERVAL = config.get("poll_interval", 5)
IDLE_TIMEOUT = config.get("idle_timeout", 60)

# ── MCP Client ────────────────────────────────────────────
MCP_MGR = load_mcp_from_config(config)
_mcp_errors = MCP_MGR.start_all()
if _mcp_errors:
    print(f"[mcp] {len(_mcp_errors)} server(s) failed to start")

# ── Intent classifier ─────────────────────────────────────
_intent_cfg = config.get("intent", {})
INTENT_CLASSIFIER = IntentClassifier(
    mode=_intent_cfg.get("mode", "keyword"),
    routes=_intent_cfg.get("routes"),
)
# Update web_search route with actual MCP tools
_web_tools = []
for name in MCP_MGR.get_all_tools():
    for t in MCP_MGR.get_all_tools()[name]:
        mcp_name = f"mcp_{name}_{t['name']}".replace("-", "_")
        _web_tools.append(mcp_name)
if _web_tools and INTENT_CLASSIFIER.routes:
    INTENT_CLASSIFIER.routes["web_search"] = _web_tools

# ── Global instances ─────────────────────────────────────
TODO = TodoManager()
SKILLS = SkillLoader(WORKDIR / "skills")
TASK_MGR = TaskManager(WORKDIR / ".tasks")
BUS = MessageBus(WORKDIR)
SCRATCHPAD = Scratchpad()
STORE = Store({"cwd": str(WORKDIR), "model": MODEL})
SESSION = SessionState(WORKDIR)

# ── Background manager ────────────────────────────────────
class BackgroundManager:
    def __init__(self):
        self.tasks: dict = {}
        self.notifications: Queue = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(target=self._exec, args=(tid, command, timeout), daemon=True).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        import subprocess
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR,
                               capture_output=True, text=True, timeout=timeout)
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update({"status": "completed", "result": output or "(no output)"})
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
        self.notifications.put({"task_id": tid, "status": self.tasks[tid]["status"],
                                "result": self.tasks[tid]["result"][:500]})

    def check(self, tid: str = None) -> str:
        if tid:
            t = self.tasks.get(tid)
            return f"[{t['status']}] {t.get('result') or '(running)'}" if t else f"Unknown: {tid}"
        return "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in self.tasks.items()) or "No bg tasks."

    def drain(self) -> list:
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs


BG = BackgroundManager()

# ── Load hooks from config ────────────────────────────────
hooks.load_from_config(config)

# ── Register tools ────────────────────────────────────────
def _register_tools():
    registry.register_many([
        build_tool("bash", "Run a shell command.",
                   {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                   lambda **kw: run_bash(kw["command"]), is_destructive=True),

        build_tool("read_file", "Read file contents.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]},
                   lambda **kw: run_read(kw["path"], kw.get("limit")), is_read_only=True, is_concurrency_safe=True),

        build_tool("write_file", "Write content to file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                   lambda **kw: run_write(kw["path"], kw["content"]), is_destructive=True),

        build_tool("edit_file", "Replace exact text in file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]},
                   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]), is_destructive=True),

        build_tool("grep", "Search files for a regex pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}, "glob_pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_grep(kw["pattern"], kw.get("glob_pattern", "**/*")), is_read_only=True, is_concurrency_safe=True),

        build_tool("glob", "List files matching a glob pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_glob(kw["pattern"]), is_read_only=True, is_concurrency_safe=True),

        build_tool("TodoWrite", "Update task tracking list.",
                   {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}, "required": ["content", "status", "activeForm"]}}}, "required": ["items"]},
                   lambda **kw: TODO.update(kw["items"])),

        build_tool("task", "Spawn a subagent for isolated work.",
                   {"type": "object", "properties": {"prompt": {"type": "string"}, "agent_type": {"type": "string", "enum": ["Explore", "general-purpose"]}}, "required": ["prompt"]},
                   lambda **kw: run_subagent(kw["prompt"], registry, client, MODEL, kw.get("agent_type", "Explore"), config.get("agents", {}).get("Explore", {}).get("maxTurns", 15)) if kw.get("agent_type") == "Explore" else run_subagent(kw["prompt"], registry, client, MODEL, kw.get("agent_type", "general-purpose"), 50)),

        build_tool("load_skill", "Load specialized knowledge by name.",
                   {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "string"}}, "required": ["name"]},
                   lambda **kw: SKILLS.load(kw["name"], kw.get("args", ""))),

        build_tool("compress", "Manually compress conversation context.",
                   {"type": "object", "properties": {}},
                   lambda **kw: "Compressing..."),

        build_tool("background_run", "Run command in background.",
                   {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]},
                   lambda **kw: BG.run(kw["command"], kw.get("timeout", 120))),

        build_tool("check_background", "Check background task status.",
                   {"type": "object", "properties": {"task_id": {"type": "string"}}},
                   lambda **kw: BG.check(kw.get("task_id"))),

        build_tool("task_create", "Create a persistent file task.",
                   {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]},
                   lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", ""))),

        build_tool("task_get", "Get task details by ID.",
                   {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
                   lambda **kw: TASK_MGR.get(kw["task_id"])),

        build_tool("task_update", "Update task status or dependencies.",
                   {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]}, "add_blocked_by": {"type": "array", "items": {"type": "integer"}}, "remove_blocked_by": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]},
                   lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by"))),

        build_tool("task_list", "List all tasks.",
                   {"type": "object", "properties": {}},
                   lambda **kw: TASK_MGR.list_all(), is_read_only=True),

        build_tool("list_skills", "List all loaded skills.",
                   {"type": "object", "properties": {}},
                   lambda **kw: SKILLS.descriptions(), is_read_only=True),

        build_tool("scratchpad_write", "Write to shared scratchpad.",
                   {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}, "required": ["filename", "content"]},
                   lambda **kw: SCRATCHPAD.write(kw["filename"], kw["content"])),

        build_tool("scratchpad_read", "Read from shared scratchpad.",
                   {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
                   lambda **kw: SCRATCHPAD.read(kw["filename"]), is_read_only=True),

        build_tool("set_objective", "Declare or update the current user objective. ONLY call when user EXPLICITLY changes the overall goal (not for small steps). The objective persists through compression — it won't be lost.",
                   {"type": "object", "properties": {"objective": {"type": "string", "description": "One sentence describing the user's current overall goal"}}, "required": ["objective"]},
                   lambda **kw: _set_objective(kw["objective"])),
    ])


_register_tools()

# ── Register MCP tools ────────────────────────────────────
_mcp_registered = MCP_MGR.register_tools(registry)
if _mcp_registered:
    print(f"[mcp] registered {len(_mcp_registered)} MCP tools")
    # Rebuild system prompt to include new tools — handled on next agent_loop iteration

def _set_objective(objective: str) -> str:
    """Persist the current objective to Store (compression-immune)."""
    STORE.set("current_objective", objective)
    return f"Objective set: {objective}"


def _on_important_event(level: str, facts: list[str]) -> None:
    """Callback: persist compression-detected important events to Store."""
    items = STORE.get("persistent_facts", [])
    # Keep max 10 persistent facts to avoid bloat
    for f in facts:
        items.append(f"[{level}] {f}")
    if len(items) > 10:
        items = items[-10:]
    STORE.set("persistent_facts", items)
    if level == "goal_declaration" and facts:
        # Also update the current objective if a goal was detected
        STORE.set("current_objective", facts[0])
    print(f"  [compression] persisted {level}: {facts}")

# ── System prompt ─────────────────────────────────────────
SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.

## How to work
- Prefer task_create/task_update/task_list for multi-step work.
- Use TodoWrite for short checklists.
- Use task for subagent delegation.
- Use load_skill for specialized knowledge.
- Use scratchpad_write/scratchpad_read for cross-agent knowledge sharing.
- Use grep and glob for code search — don't use bash for this.
- Use memory_add to preserve important knowledge, decisions, user preferences,
  and lessons learned across sessions. The memory goes through a pipeline
  (validate → normalize → deduplicate → policy check) before being stored.
- Use memory_search (semantic + keyword hybrid) to recall past context
  before starting a task. Use memory_list to browse stored memories.
- The Memory OS auto-learns: it extracts knowledge from conversations,
  scores importance dynamically, and performs self-reflection to merge
  duplicates and resolve conflicts.

## Memory OS
Memory OS preserves knowledge across sessions with automatic learning:
- memory_add(type, content, summary?, tags?) — Save a memory
- memory_search(query, type?) — Hybrid semantic+keyword search (Phase 2)
- memory_list(type?, state?, limit?) — List memories
- memory_get(id) — Read a specific memory
- memory_update(id, **fields) — Update a memory
- memory_delete(id) — Soft-delete a memory
- memory_archive(id) — Archive a memory
- memory_extract(conversation_text?) — Extract knowledge from conversation
- memory_reflect() — Run self-reflection (merge/conflict/refine/split)
- memory_stats() — Memory system health dashboard

## Available skills
{SKILLS.descriptions()}

## Compression
Conversation history is managed with three-tier compression:
1. micro-compact (clear old tool results)
2. context collapse (summarize middle rounds)
3. auto-compact (full summary)

Use the 'compress' tool to manually trigger compression."""

# ── Compression LLM call (shared by M3 stages) ────────────
def _compress_llm(prompt: str) -> str:
    """LLM call wrapper for compression stages (ContextCollapse, AutoCompact)."""
    resp = client.messages.create(
        model=MODEL,
        system="Summarize concisely.",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return resp.content[0].text

# ── REPL ──────────────────────────────────────────────────
def main():
    print(f"agent-core v2.0 — Reference Agent")
    print(f"  Model: {MODEL}")
    print(f"  Skills: {len(SKILLS.skills)} loaded")
    print(f"  Hooks: {sum(len(h) for h in hooks._hooks.values())} registered")
    print(f"  Scratchpad: {SCRATCHPAD.path}")

    # ── Memory OS (M6) ──────────────────────────────────
    memory_core = MemoryCore(db_path=WORKDIR / ".memory")
    loaded = memory_core.load()
    if loaded:
        print(f"  Memory: {loaded} entries loaded from {memory_core.store.db_file}")
    else:
        print(f"  Memory: ready ({memory_core.store.db_file})")

    # M7: Retrieval Engine
    ret_cfg = RetrievalConfig(sync_fallback=True)  # Sync fallback until Worker starts
    retrieval_engine = memory_core.init_retrieval(config=ret_cfg)
    # Start async worker (switches from sync_fallback to async)
    if retrieval_engine._worker:
        retrieval_engine._worker.start()
    print(f"  Retrieval: {retrieval_engine.vector_index.stats()['count']} vectors indexed")

    memory_layer = MemoryLayer(store=memory_core.store, max_entries=5, engine=retrieval_engine)

    # Register memory tools for agent use
    mem_tools = build_memory_tools(memory_core.store, memory_core.pipeline, retrieval_engine)
    registry.register_many(mem_tools)
    print(f"  Memory Tools: {len(mem_tools)} registered")

    # M8: Importance Engine — dynamic scoring + access tracking + feedback
    importance_engine = memory_core.init_importance()
    print(f"  Importance: dynamic scoring active, "
          f"decay_half_life={importance_engine.decay._config.freshness_half_life_days}d")

    # Shared LLM call for M9/M10
    def _memory_llm(prompt: str) -> str:
        resp = client.messages.create(
            model=MODEL,
            system="You are a knowledge manager. Output valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        return resp.content[0].text

    # M9: Intelligence Engine — auto-extraction + self-reflection
    intelligence_engine = memory_core.init_intelligence(
        llm_call=_memory_llm,
    )
    print(f"  Intelligence: extractor + 4 reflection strategies "
          f"(merge/conflict/refine/split) ready")
    trigger_names = [e.value for e in intelligence_engine.trigger._subscribers if intelligence_engine.trigger._subscribers[e]]
    print(f"  Intelligence triggers: {trigger_names}")

    # M10: Lifecycle Engine — background archiving + compression + GC
    lifecycle_engine = memory_core.init_lifecycle(
        llm_call=_memory_llm,
    )
    print(f"  Lifecycle: 5-state machine + 3 compressors + GC worker running")

    # Feed M9 Intelligence into agent loop: auto-extract after each task
    # Trigger daemon runs in background, processes conversation -> memory entries
    print()

    # ── Context Engine (M1-M5) ──────────────────────────
    budget_cfg = BudgetConfig(
        total_budget=TOKEN_THRESHOLD,
        instruction_ratio=0.10,
        conversation_ratio=0.90,
    )

    # M2: Workspace + File Cache
    workspace = WorkspaceLayer(cwd=str(WORKDIR))
    file_cache = FileCacheLayer(max_files=20, max_lines=150)

    # M3: Budget + Compression
    token_budget = Budget(name="token", total=TOKEN_THRESHOLD, unit="tokens")
    alloc_policy = BudgetPolicy([
        BudgetAllocation("instruction", 0.10),
        BudgetAllocation("workspace", 0.05),
        BudgetAllocation("memory", 0.05),      # M6
        BudgetAllocation("file_cache", 0.05),
        BudgetAllocation("summary", 0.15),
        BudgetAllocation("conversation", 0.60),
    ])
    budget_mgr = BudgetManager(budgets=[token_budget], policy=alloc_policy)

    compress_policy = CompressionPolicy()
    compress_policy.add_rule(
        OverBudgetRule(
            layer_name="conversation",
            max_tier=3,
            target_ratio=0.50,
            min_excess_ratio=0.10,
            min_consecutive=2,  # Avoid thrashing on borderline cases
        )
    )

    summarizer = LLMSummarizer(llm_call=_compress_llm)

    compress_stages = [
        MicroCompactStage(keep_recent=KEEP_RECENT),
        ContextCollapseStage(keep_head=3, keep_tail=3),
        AutoCompactStage(keep_recent_rounds=5),
    ]
    compress_pipeline = CompressionPipeline(stages=compress_stages)

    # Circuit breaker: after 3 consecutive LLM failures, wait 60s before retrying
    circuit_breaker = CircuitBreaker(max_failures=3, reset_timeout=60.0)

    # M4: Context Selection Pipeline
    def _calc_budget(ratio: float) -> int:
        return int(TOKEN_THRESHOLD * ratio)

    selection_pipeline = SelectionPipeline(
        collectors=[
            InstructionCollector(),
            WorkspaceCollector(),
            MemoryCollector(store=memory_core.store),  # M6
            SummaryCollector(),
            FileCacheCollector(),
            ConversationCollector(),
        ],
        rankers=[PriorityRanker()],
        policy=BudgetSelectionPolicy([
            TokenConstraint(source="instruction", max_tokens=_calc_budget(0.10), reserved=True),
            TokenConstraint(source="workspace",   max_tokens=_calc_budget(0.05), reserved=True),
            TokenConstraint(source="memory",      max_tokens=_calc_budget(0.05), reserved=False),  # M6
            TokenConstraint(source="file_cache",  max_tokens=_calc_budget(0.05), reserved=False),
            TokenConstraint(source="summary",     max_tokens=_calc_budget(0.15), reserved=False),
            TokenConstraint(source="conversation", max_tokens=_calc_budget(0.60), reserved=False),
        ]),
    )

    # M5: Recovery + Audit
    recovery = RecoveryEngine(store=STORE)
    audit_log = AuditLog(store=STORE, max_entries=200)

    # ── Assemble Orchestrator ────────────────────────────
    orchestrator = ContextOrchestrator(
        store=STORE,
        base_system=SYSTEM,
        skills_descriptions=SKILLS.descriptions(),
        budget=budget_cfg,
        on_important_fn=lambda level, facts: _on_important_event(level, facts),
        workspace=workspace,
        file_cache=file_cache,
        # M6
        memory_layer=memory_layer,
        # M3
        budget_manager=budget_mgr,
        compression_policy=compress_policy,
        compression_pipeline=compress_pipeline,
        summarizer=summarizer,
        llm_call=_compress_llm,
        circuit_breaker=circuit_breaker,
        # M4
        selection_pipeline=selection_pipeline,
    )
    # Backward compat: history aliases orchestrator's message list
    history = orchestrator.get_messages()

    print(f"  Workspace: {workspace.cwd} ({workspace.git_branch or 'no git'})")
    print(f"  File Cache: {file_cache.size} files cached")
    print(f"  Memory: {memory_core.active_count} active entries")

    while True:
        try:
            query = input("\033[36ms_full >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        # REPL commands
        if query.strip() == "/compact":
            if orchestrator.has_compression:
                # Reset circuit breaker so manual compact can retry
                if hasattr(orchestrator, '_circuit_breaker') and orchestrator._circuit_breaker:
                    cb = orchestrator._circuit_breaker
                    cb.reset()
                    print(f"  [compact] circuit breaker reset ({cb})")
                print(f"  [compact] before: {orchestrator.token_count} tokens")
                ran = orchestrator.tick()
                print(f"  [compact] after: {orchestrator.token_count} tokens"
                      f"{' (compression executed)' if ran else ' (within budget)'}")
            else:
                print("[compact] M3 compression not configured")
            continue
        if query.strip() == "/tasks":
            print(TASK_MGR.list_all())
            continue
        if query.strip() == "/skills":
            print(SKILLS.descriptions())
            continue
        if query.strip() == "/hooks":
            for event, h_list in hooks._hooks.items():
                if h_list:
                    print(f"  {event}: {len(h_list)} hooks")
            continue
        if query.strip() == "/memory":
            stats = memory_core.stats()
            print(f"Memory: {stats['active']} active, {stats['archived']} archived, "
                  f"{stats['deleted']} deleted ({stats['total']} total)")
            if stats.get("by_type"):
                print(f"  By type: {stats['by_type']}")
            if stats.get("projects"):
                print(f"  Projects: {stats['projects']}")
            # M7
            if retrieval_engine:
                rstats = retrieval_engine.stats()
                vi = rstats['vector_index']
                print(f"  M7 Retrieval: {vi['count']} vectors dim={vi['dim']}, "
                      f"worker={'running' if rstats['worker'].get('running') else 'stopped'}")
            # M8
            if importance_engine:
                istats = importance_engine.stats()
                imp = istats.get('importance_distribution', {})
                print(f"  M8 Importance: avg={imp.get('avg', 0):.2f}, "
                      f"accesses={istats.get('tracker', {}).get('total_accesses', 0)}, "
                      f"running={istats.get('running', False)}")
            # M9
            if intelligence_engine:
                intel_stats = intelligence_engine.stats()
                ext = intel_stats.get('extractor', {})
                ref = intel_stats.get('reflector', {})
                print(f"  M9 Intelligence: extracted={ext.get('total_extracted', 0)}, "
                      f"reflected={ref.get('total_reflected', 0)}, "
                      f"running={intel_stats.get('running', False)}")
            # M10
            if lifecycle_engine:
                lc_stats = lifecycle_engine.stats()
                sm = lc_stats.get('state_machine', {})
                print(f"  M10 Lifecycle: running={lc_stats.get('running', False)}, "
                      f"transitions={sm.get('total_transitions', 0)}")
            continue

        # ▶ UserPromptSubmit hook
        hook_result = hooks.execute("UserPromptSubmit", HookInput(
            event="UserPromptSubmit", user_message=query,
        ))
        if hook_result.is_blocked:
            print(f"[blocked: {hook_result.reason}]")
            continue

        if hook_result.additional_context:
            query = query + "\n\n<context>\n" + hook_result.additional_context + "\n</context>"

        orchestrator.add_message("user", query)

        # Run agent loop
        agent_loop(
            history,
            registry,
            client,
            model=MODEL,
            base_system=SYSTEM,
            skills_descriptions=SKILLS.descriptions(),
            hook_manager=hooks,
            token_threshold=TOKEN_THRESHOLD,
            keep_recent=KEEP_RECENT,
            bg_drain_fn=BG.drain,
            inbox_check_fn=lambda: BUS.read_inbox("lead"),
            classify_intent_fn=lambda q: INTENT_CLASSIFIER.classify(q),
            filter_tools_fn=lambda intent, tools: filter_by_intent(registry, intent, INTENT_CLASSIFIER.routes),
            orchestrator=orchestrator,
        )

        # Display response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

    # Cleanup
    SCRATCHPAD.cleanup()
    MCP_MGR.stop_all()
    print("Session ended.")


if __name__ == "__main__":
    main()
