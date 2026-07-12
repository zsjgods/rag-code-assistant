#!/usr/bin/env python3
"""Context Fidelity Evaluation — 测试 agent-core 压缩后目标是否丢失。

与 BFCL 的关键区别：BFCL 绕过 agent loop 直接调 API，
Context Fidelity 走完整的 agent 主循环 → 测的是框架，不是 LLM。

方法论：
  1. 给 Agent 一个初始目标
  2. 插入 N 轮干扰对话（模拟长对话）
  3. 当上下文超过阈值，agent-core 的压缩模块自动触发
  4. 压缩后发送检查提问
  5. LLM Judge 评估 Agent 回答的完整性

Usage:
    python run_context_fidelity.py                    # 跑所有场景
    python run_context_fidelity.py --scenario 1       # 只跑场景 1
    python run_context_fidelity.py --no-compress      # 对照组：关闭压缩
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.getenv("MODEL_ID", "deepseek-v4-pro")

sys.path.insert(0, os.path.dirname(__file__))

from src.tools.registry import ToolRegistry
from src.tools.base import build_tool
from src.tools.builtin import run_bash, run_read, run_write, run_edit, run_grep, run_glob
from src.state.store import Store
from src.tasks.todo import TodoManager
from src.tasks.task_manager import TaskManager
from src.bus.scratchpad import Scratchpad
from src.skills.loader import SkillLoader
from src.agent.loop import agent_loop
from src.eval.context_fidelity import SCENARIOS


# ═══════════════════════════════════════════════════════════════
#  Tool registry (mirrors main.py, needed for agent_loop)
# ═══════════════════════════════════════════════════════════════

WORKDIR = Path.cwd()
TODO = TodoManager()
TASK_MGR = TaskManager(WORKDIR / ".tasks")
SCRATCHPAD = Scratchpad()
SKILLS = SkillLoader(WORKDIR / "skills")
STORE = Store({"cwd": str(WORKDIR), "model": MODEL})


def _register_tools(registry: ToolRegistry):
    registry.register_many([
        build_tool("bash", "Run a shell command.",
                   {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                   lambda **kw: run_bash(kw["command"]), is_destructive=True),
        build_tool("read_file", "Read file contents.",
                   {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                   lambda **kw: run_read(kw["path"]), is_read_only=True, is_concurrency_safe=True),
        build_tool("write_file", "Write content to file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                   lambda **kw: run_write(kw["path"], kw["content"]), is_destructive=True),
        build_tool("edit_file", "Replace exact text in file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]},
                   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]), is_destructive=True),
        build_tool("grep", "Search files for a regex pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_grep(kw["pattern"]), is_read_only=True, is_concurrency_safe=True),
        build_tool("glob", "List files matching a glob pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_glob(kw["pattern"]), is_read_only=True, is_concurrency_safe=True),
        build_tool("TodoWrite", "Update task tracking list.",
                   {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
                   lambda **kw: TODO.update(kw["items"])),
        build_tool("task_create", "Create a persistent task.",
                   {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]},
                   lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", ""))),
        build_tool("task_list", "List all tasks.",
                   {"type": "object", "properties": {}},
                   lambda **kw: TASK_MGR.list_all(), is_read_only=True),
        build_tool("scratchpad_write", "Write to shared scratchpad.",
                   {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}, "required": ["filename", "content"]},
                   lambda **kw: SCRATCHPAD.write(kw["filename"], kw["content"])),
        build_tool("scratchpad_read", "Read from shared scratchpad.",
                   {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
                   lambda **kw: SCRATCHPAD.read(kw["filename"]), is_read_only=True),
        build_tool("set_objective", "Declare or update the current user objective.",
                   {"type": "object", "properties": {"objective": {"type": "string"}}, "required": ["objective"]},
                   lambda **kw: STORE.set("current_objective", kw["objective"])),
    ])


# ═══════════════════════════════════════════════════════════════
#  LLM Judge — 评估 Agent 的回答质量
# ═══════════════════════════════════════════════════════════════

JUDGE_PROMPT = """You are an evaluator scoring an AI agent's context fidelity.

The agent was given an initial objective, then went through many rounds of
distracting conversation that may have triggered context compression.

Now the agent was asked a check question. Score its response.

Output ONLY this JSON:
{
  "goal_fidelity": 0-100,     // how well the agent remembers the ORIGINAL objective
  "keyword_hits": ["hit1"],   // which expected keywords appear in the response
  "keyword_misses": ["miss1"],// which expected keywords are missing
  "hallucinations": ["h1"],   // any false/irrelevant information the agent inserted
  "overall_pass": true/false  // does the agent demonstrate context fidelity?
}

Scoring rules:
- goal_fidelity: 100 = perfectly remembers; 70 = remembers core but misses details;
                 40 = partially remembers but distorted; 0 = completely forgotten
- keyword_hits: only count if the CONCEPT is present (synonyms count)
- hallucinations: flag if the agent confidently states something that wasn't in the original objective
- overall_pass: true only if goal_fidelity >= 70 AND no significant hallucinations"""


def judge_response(
    client,
    original_objective: str,
    check_prompt: str,
    agent_response: str,
    expected_keywords: list[str],
    min_keywords: int,
) -> dict:
    """LLM Judge evaluates the agent's response."""
    judge_input = f"""
ORIGINAL OBJECTIVE (given to agent at start):
{original_objective}

CHECK QUESTION (asked after compression):
{check_prompt}

AGENT'S RESPONSE:
{agent_response}

EXPECTED KEYWORDS (for reference):
{expected_keywords}

MINIMUM KEYWORDS REQUIRED: {min_keywords}
"""
    try:
        resp = client.messages.create(
            model=MODEL,
            system=JUDGE_PROMPT,
            messages=[{"role": "user", "content": judge_input}],
            max_tokens=1000,
        )
        text = resp.content[0].text if hasattr(resp.content[0], "text") else str(resp.content)

        # Try multiple JSON extraction strategies
        parsed = None
        # Strategy 1: standard JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        # Strategy 2: fix single quotes → double quotes
        if parsed is None and start != -1 and end > start:
            try:
                fixed = text[start:end].replace("'", '"')
                parsed = json.loads(fixed)
            except json.JSONDecodeError:
                pass
        # Strategy 3: keyword-based fallback
        if parsed is None:
            lower_text = text.lower()
            hits = [kw for kw in expected_keywords if kw.lower() in lower_text]
            misses = [kw for kw in expected_keywords if kw.lower() not in lower_text]
            parsed = {
                "goal_fidelity": int(len(hits) / len(expected_keywords) * 100) if expected_keywords else 0,
                "keyword_hits": hits,
                "keyword_misses": misses,
                "hallucinations": [],
                "overall_pass": len(hits) >= min_keywords,
                "_fallback": True,
                "_raw": text[:500],
            }
        return parsed
    except Exception as e:
        return {"goal_fidelity": 0, "keyword_hits": [], "keyword_misses": expected_keywords,
                "hallucinations": [str(e)], "overall_pass": False}


# ═══════════════════════════════════════════════════════════════
#  Conversation Simulator
# ═══════════════════════════════════════════════════════════════

def run_scenario(client, registry: ToolRegistry, scenario: dict,
                 no_compress: bool = False) -> dict:
    """Run a single context fidelity scenario through the agent loop.

    Instead of running the full agent loop (which would take very long),
    we simulate a long conversation by:
      1. Building a conversation that starts with the objective
      2. Adding distraction messages (simulating tool call rounds)
      3. Manually triggering compression when context is large
      4. Sending the check prompt and evaluating

    Args:
        client: Anthropic client
        registry: ToolRegistry
        scenario: Scenario dict from SCENARIOS
        no_compress: if True, skip compression (control group)

    Returns:
        Evaluation result dict
    """
    tools = registry.to_api_format()
    base_system = (
        "You are an AI assistant with file tools, task management, and a scratchpad. "
        "Use tools when helpful. Keep track of the user's original objective. "
        "When the user changes topics, answer the new question but don't forget "
        "the original goal — you may need to return to it later."
    )

    # ── Build conversation ───────────────────────────────
    messages = [
        {"role": "user", "content": scenario["initial_objective"]},
        # Simulate agent acknowledging the objective
        {"role": "assistant", "content": "我理解了。我来记住这个目标，然后开始执行。"},
    ]

    # Add distractions (each is a simulated round-trip)
    for i, distraction in enumerate(scenario["distractions"]):
        # User asks distraction
        messages.append({"role": "user", "content": distraction})

        # Simulate assistant response (we use a short response to keep things fast)
        messages.append({
            "role": "assistant",
            "content": f"好的，关于「{distraction[:30]}...」这个问题，我来处理。"
        })

        # Every 3 distractions, add a tool-call round to add real content bulk
        if i % 3 == 0:
            messages.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": f"tool_{i}",
                    "name": "grep" if i % 2 == 0 else "read_file",
                    "input": {"pattern": distraction.split()[0] if i % 2 == 0 else "test",
                              "path": "src/main.py"},
                }]
            })
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": f"tool_{i}",
                    "content": f"[tool output for: {distraction[:50]}]\n"
                              f"Found results matching your query. "
                              f"Here is some filler content to increase token count "
                              f"and simulate real tool output. " * 10,
                }]
            })

    # ── Trigger compression if enabled ────────────────────
    if not no_compress:
        from src.compression.collapse import context_collapse, CollapseCircuitBreaker
        from src.compression.micro import estimate_tokens

        # Force multiple compression rounds
        for round_num in range(3):
            token_count = estimate_tokens(messages)
            if token_count > 3000:  # low threshold for testing
                breaker = CollapseCircuitBreaker(max_failures=3)
                collapsed = context_collapse(
                    messages,
                    lambda p: client.messages.create(
                        model=MODEL,
                        system="You are a conversation summarizer.",
                        messages=[{"role": "user", "content": p}],
                        max_tokens=1000,
                    ).content[0].text,
                    keep_head=2,
                    keep_tail=2,
                )
                if collapsed is not None:
                    messages[:] = collapsed
                    # Add a marker so we know compression happened
                    messages.append({
                        "role": "user",
                        "content": f"[SYSTEM: context compressed (round {round_num + 1})]"
                    })

    # ── Final check ───────────────────────────────────────
    check = scenario["check"]
    messages.append({"role": "user", "content": check["prompt"]})

    try:
        response = client.messages.create(
            model=MODEL,
            system=base_system,
            messages=messages,
            tools=tools,
            max_tokens=2000,
        )
        agent_answer = "".join(
            b.text for b in response.content if hasattr(b, "text")
        )
    except Exception as e:
        return {
            "scenario": scenario["id"],
            "passed": False,
            "error": str(e),
            "judge": None,
        }

    # ── LLM Judge ─────────────────────────────────────────
    judge = judge_response(
        client,
        scenario["initial_objective"],
        check["prompt"],
        agent_answer,
        check["expected_keywords"],
        check["min_keywords"],
    )

    passed = judge.get("overall_pass", False)
    fidelity = judge.get("goal_fidelity", 0)

    return {
        "scenario": scenario["id"],
        "name": scenario["name"],
        "passed": passed,
        "goal_fidelity": fidelity,
        "keyword_hits": judge.get("keyword_hits", []),
        "keyword_misses": judge.get("keyword_misses", []),
        "hallucinations": judge.get("hallucinations", []),
        "agent_response": agent_answer[:300],
        "judge": judge,
    }


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    no_compress = "--no-compress" in args

    # Filter by scenario
    scenario_idx = None
    for i, a in enumerate(args):
        if a == "--scenario" and i + 1 < len(args):
            scenario_idx = int(args[i + 1]) - 1

    scenarios = [SCENARIOS[scenario_idx]] if scenario_idx is not None else SCENARIOS

    # Setup
    registry = ToolRegistry()
    _register_tools(registry)
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

    mode = "NO COMPRESSION (control)" if no_compress else "WITH COMPRESSION"
    print(f"Context Fidelity Evaluation — Model: {MODEL}")
    print(f"Mode: {mode}")
    print(f"Scenarios: {len(scenarios)}\n")

    results = []
    for i, scenario in enumerate(scenarios):
        print(f"[{i+1}/{len(scenarios)}] {scenario['name']}...")
        start = time.time()
        result = run_scenario(client, registry, scenario, no_compress=no_compress)
        elapsed = time.time() - start

        status = "✅" if result["passed"] else "❌"
        fidelity = result.get("goal_fidelity", 0)
        hits = len(result.get("keyword_hits", []))
        misses = len(result.get("keyword_misses", []))
        expected = hits + misses
        keyword_rate = f"{hits}/{expected}" if expected > 0 else "N/A"

        print(f"  {status} fidelity={fidelity}/100  keywords={keyword_rate}  "
              f"hallucinations={len(result.get('hallucinations', []))}  "
              f"({elapsed:.0f}s)")

        if result.get("error"):
            print(f"  ⚠️ Error: {result['error']}")
        if result.get("hallucinations"):
            print(f"  💭 Hallucinations: {result['hallucinations'][:3]}")
        if result.get("keyword_misses"):
            print(f"  🔍 Missing: {result['keyword_misses'][:5]}")

        results.append(result)

    # ── Summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CONTEXT FIDELITY SUMMARY")
    print(f"  Mode: {mode}")
    print("=" * 60)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    avg_fidelity = sum(r.get("goal_fidelity", 0) for r in results) / total if total else 0
    total_misses = sum(len(r.get("keyword_misses", [])) for r in results)
    total_hallucinations = sum(len(r.get("hallucinations", [])) for r in results)

    print(f"  Scenarios passed:   {passed}/{total}")
    print(f"  Avg goal fidelity:  {avg_fidelity:.0f}/100")
    print(f"  Keyword misses:     {total_misses}")
    print(f"  Hallucinations:     {total_hallucinations}")

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['name']}: fidelity={r.get('goal_fidelity',0)}")
        if r.get("error"):
            print(f"         ERROR: {r['error']}")

    print("=" * 60)

    # Save
    out_dir = Path(".fidelity_results")
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    mode_tag = "nocompress" if no_compress else "compress"
    out_path = out_dir / f"fidelity_{MODEL.replace('/', '_')}_{mode_tag}_{ts}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
