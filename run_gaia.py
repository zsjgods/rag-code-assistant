#!/usr/bin/env python3
"""Run GAIA benchmark evaluation on agent-core.

Usage:
    # First download dataset:
    python -c "from src.eval.gaia_loader import download_gaia; download_gaia()"

    # Run evaluation:
    python run_gaia.py                    # all levels, all questions
    python run_gaia.py --level 1          # only level 1 (easy)
    python run_gaia.py --max 10           # first 10 questions
    python run_gaia.py --level 1 --max 5  # level 1, first 5
"""

import os
import sys
import time
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-6-20250514")

sys.path.insert(0, os.path.dirname(__file__))
from src.tools.registry import ToolRegistry, registry
from src.tools.base import build_tool
from src.tools.builtin import run_bash, run_read, run_write, run_edit, run_grep, run_glob
from src.state.store import Store
from src.tasks.todo import TodoManager
from src.skills.loader import SkillLoader
from src.tasks.task_manager import TaskManager
from src.bus.scratchpad import Scratchpad
from src.bus.mcp_client import MCPClientManager, load_mcp_from_config
from src.config.loader import load_config
from src.eval.gaia_loader import load_gaia, download_gaia, score_answer


def _register_all_tools():
    """Register built-in tools (mirrors main.py)."""
    WORKDIR = Path.cwd()
    TODO = TodoManager()
    TASK_MGR = TaskManager(WORKDIR / ".tasks")
    SCRATCHPAD = Scratchpad()
    SKILLS = SkillLoader(WORKDIR / "skills")
    STORE = Store({"cwd": str(WORKDIR), "model": MODEL})

    registry.register_many([
        build_tool("bash", "Run a shell command.",
                   {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                   lambda **kw: run_bash(kw["command"]), is_destructive=True),
        build_tool("read_file", "Read file contents.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]},
                   lambda **kw: run_read(kw["path"], kw.get("limit")), is_read_only=True),
        build_tool("grep", "Search files for a regex pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}, "glob_pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_grep(kw["pattern"], kw.get("glob_pattern", "**/*")), is_read_only=True),
        build_tool("glob", "List files matching a glob pattern.",
                   {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                   lambda **kw: run_glob(kw["pattern"]), is_read_only=True),
        build_tool("write_file", "Write content to file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                   lambda **kw: run_write(kw["path"], kw["content"]), is_destructive=True),
        build_tool("edit_file", "Replace exact text in file.",
                   {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]},
                   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]), is_destructive=True),
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


def run_gaia_question(client, question: dict, max_turns: int = 10) -> dict:
    """Run a single GAIA question through the agent.

    Args:
        client: Anthropic client
        question: GAIA question dict
        max_turns: maximum ReAct iterations

    Returns:
        {"predicted": str, "ground_truth": str, "turns": int, "correct": bool}
    """
    tools = registry.to_api_format()

    task_text = question["question"]
    if question.get("file_name"):
        task_text += f"\n\nAttached file: {question['file_name']}"

    system = (
        "You are an AI assistant solving real-world tasks. "
        "You have access to web search and file tools. "
        "Think step by step. When you have the final answer, output it on a new line "
        "prefixed with 'FINAL ANSWER: '."
    )

    messages = [{"role": "user", "content": task_text}]
    predicted = ""
    turns = 0

    for _ in range(max_turns):
        turns += 1
        try:
            response = client.messages.create(
                model=MODEL,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=2000,
            )
        except Exception as e:
            predicted = f"API_ERROR: {e}"
            break

        messages.append({"role": "assistant", "content": response.content})

        # Check for stop
        if response.stop_reason != "tool_use":
            text = "".join(
                b.text for b in response.content if hasattr(b, "text")
            )
            # Extract final answer
            if "FINAL ANSWER:" in text:
                idx = text.index("FINAL ANSWER:") + len("FINAL ANSWER:")
                predicted = text[idx:].strip().split("\n")[0].strip()
            else:
                predicted = text.strip()
            break

        # Execute tools
        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                try:
                    output = registry.execute(block.name, **dict(block.input))
                except Exception as e:
                    output = f"Error: {e}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:30000],
                })

        messages.append({"role": "user", "content": tool_results})

    ground_truth = question.get("final_answer", "")

    return {
        "task_id": question["task_id"],
        "level": question["level"],
        "question": question["question"][:100],
        "predicted": predicted[:500],
        "ground_truth": ground_truth,
        "turns": turns,
        "correct": score_answer(predicted, ground_truth)["correct"],
    }


def main():
    # Parse args
    args = sys.argv[1:]
    levels = None
    max_q = None

    if "--level" in args:
        idx = args.index("--level")
        levels = [int(args[idx + 1])] if idx + 1 < len(args) else None
    if "--max" in args:
        idx = args.index("--max")
        max_q = int(args[idx + 1]) if idx + 1 < len(args) else None

    # Load config + start MCP
    config = load_config(Path.cwd())
    mcp_mgr = load_mcp_from_config(config)
    mcp_errors = mcp_mgr.start_all()
    if mcp_errors:
        print(f"MCP errors: {mcp_errors}")

    # Register tools
    _register_all_tools()
    mcp_registered = mcp_mgr.register_tools(registry)
    print(f"Tools: {len(registry.names())} built-in + {len(mcp_registered)} MCP\n")

    # Load GAIA data
    data_path = Path(".gaia_data/gaia_validation.json")
    if not data_path.exists():
        print("Downloading GAIA validation set...")
        download_gaia("validation")

    questions = load_gaia(data_path, levels=levels, max_questions=max_q)
    level_str = f"Level {levels[0]}" if levels else "All levels"
    print(f"Running {len(questions)} questions ({level_str})...\n")

    # Run evaluation
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
    results = []
    level_results = {1: [], 2: [], 3: []}

    for i, q in enumerate(questions):
        print(f"[{i+1}/{len(questions)}] L{q['level']}: {q['question'][:80]}...")
        result = run_gaia_question(client, q)
        results.append(result)
        level_results[q["level"]].append(result)

        status = "OK" if result["correct"] else "X"
        print(f"       => {status}  turns={result['turns']}  "
              f"pred={result['predicted'][:80]}")

    # Summary
    print("\n" + "=" * 60)
    print("GAIA EVALUATION SUMMARY")
    print("=" * 60)

    total_correct = sum(1 for r in results if r["correct"])
    total = len(results)
    print(f"  Overall: {total_correct}/{total} ({total_correct/total*100:.0f}%)")

    for level in [1, 2, 3]:
        lr = level_results[level]
        if lr:
            correct = sum(1 for r in lr if r["correct"])
            print(f"  Level {level}: {correct}/{len(lr)} ({correct/len(lr)*100:.0f}%)")

    print(f"  Avg turns: {sum(r['turns'] for r in results)/len(results):.1f}")
    print("=" * 60)

    mcp_mgr.stop_all()


if __name__ == "__main__":
    main()
