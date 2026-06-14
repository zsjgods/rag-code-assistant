#!/usr/bin/env python3
"""s_full.py — Reference Agent implementing Claude Code core architecture.

Hook system, three-tier compression, tool isolation, skill loading,
task management, background execution, teammate system.

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
from src.compression.micro import microcompact, estimate_tokens
from src.compression.collapse import context_collapse
from src.compression.auto import auto_compact, CompressionPipeline
from src.skills.loader import SkillLoader
from src.state.store import Store, ToolUseContext
from src.bus.message_bus import MessageBus
from src.bus.scratchpad import Scratchpad
from src.tasks.todo import TodoManager
from src.tasks.task_manager import TaskManager
from src.config.loader import load_config
from src.recovery.error_handler import ErrorRecoveryPipeline
from src.recovery.session import SessionState

# ── Load config ──────────────────────────────────────────
config = load_config(WORKDIR)
TOKEN_THRESHOLD = config.get("token_threshold", 100000)
KEEP_RECENT = config.get("keep_recent_tools", 3)
POLL_INTERVAL = config.get("poll_interval", 5)
IDLE_TIMEOUT = config.get("idle_timeout", 60)

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
    ])


_register_tools()

# ── System prompt ─────────────────────────────────────────
SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.

## How to work
- Prefer task_create/task_update/task_list for multi-step work.
- Use TodoWrite for short checklists.
- Use task for subagent delegation.
- Use load_skill for specialized knowledge.
- Use scratchpad_write/scratchpad_read for cross-agent knowledge sharing.
- Use grep and glob for code search — don't use bash for this.

## Available skills
{SKILLS.descriptions()}

## Compression
Conversation history is managed with three-tier compression:
1. micro-compact (clear old tool results)
2. context collapse (summarize middle rounds)
3. auto-compact (full summary)

Use the 'compress' tool to manually trigger compression."""

# ── Compression pipeline ──────────────────────────────────
def _fallback_llm(prompt: str) -> str:
    """LLM call wrapper for compression."""
    resp = client.messages.create(
        model=MODEL,
        system="Summarize concisely.",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return resp.content[0].text

compression = CompressionPipeline(
    llm_call=_fallback_llm,
    token_threshold=TOKEN_THRESHOLD,
    keep_recent=KEEP_RECENT,
)

# ── REPL ──────────────────────────────────────────────────
def main():
    print(f"s_full.py v2.0 — Reference Agent")
    print(f"  Model: {MODEL}")
    print(f"  Skills: {len(SKILLS.skills)} loaded")
    print(f"  Hooks: {sum(len(h) for h in hooks._hooks.values())} registered")
    print(f"  Scratchpad: {SCRATCHPAD.path}")
    print()

    history: list = []

    while True:
        try:
            query = input("\033[36ms_full >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        # REPL commands
        if query.strip() == "/compact":
            if history:
                print("[manual compact]")
                history[:] = compression.compress(history)
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

        # ▶ UserPromptSubmit hook
        hook_result = hooks.execute("UserPromptSubmit", HookInput(
            event="UserPromptSubmit", user_message=query,
        ))
        if hook_result.is_blocked:
            print(f"[blocked: {hook_result.reason}]")
            continue

        if hook_result.additional_context:
            query = query + "\n\n<context>\n" + hook_result.additional_context + "\n</context>"

        history.append({"role": "user", "content": query})

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
    print("Session ended.")


if __name__ == "__main__":
    main()
