#!/usr/bin/env python3
"""Run agent function calling evaluation.

Usage:
    python run_eval.py                    # run all 30 cases
    python run_eval.py --simple           # run only simple cases
    python run_eval.py --list             # list all test cases without running
"""

import os
import sys

# Fix Windows GBK encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from anthropic import Anthropic

# Bootstrap
load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-6-20250514")

# Import agent-core
sys.path.insert(0, os.path.dirname(__file__))
from src.tools.registry import registry
from src.tools.base import build_tool
from src.tools.builtin import run_bash, run_read, run_write, run_edit, run_grep, run_glob
from src.eval.test_cases import get_all_cases, SIMPLE, IRRELEVANT, MULTIPLE, PARALLEL
from src.eval.runner import run_benchmark


def _register_tools():
    """Register tools for evaluation (mirrors main.py's registration)."""
    from src.state.store import Store
    from src.tasks.todo import TodoManager
    from src.skills.loader import SkillLoader
    from src.tasks.task_manager import TaskManager
    from src.bus.scratchpad import Scratchpad
    from src.agent.loop import run_subagent
    from pathlib import Path
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

        build_tool("memory_search", "Search memory with hybrid semantic+keyword retrieval.",
                   {"type": "object", "properties": {"query": {"type": "string"}, "type": {"type": "string"}}, "required": ["query"]},
                   lambda **kw: f"Memory search results (mock)", is_read_only=True, is_concurrency_safe=True),

        build_tool("memory_list", "List memories by type, state, or limit.",
                   {"type": "object", "properties": {"type": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "integer"}}},
                   lambda **kw: f"Memory list (mock)", is_read_only=True, is_concurrency_safe=True),

        build_tool("TodoWrite", "Update task tracking list.",
                   {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
                   lambda **kw: TODO.update(kw["items"])),

        build_tool("task", "Spawn a subagent for isolated work.",
                   {"type": "object", "properties": {"prompt": {"type": "string"}, "agent_type": {"type": "string"}}, "required": ["prompt"]},
                   lambda **kw: "Subagent result (mock)"),

        build_tool("load_skill", "Load specialized knowledge by name.",
                   {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "string"}}, "required": ["name"]},
                   lambda **kw: SKILLS.load(kw["name"], kw.get("args", ""))),

        build_tool("compress", "Manually compress conversation context.",
                   {"type": "object", "properties": {}},
                   lambda **kw: "Compressing (mock)"),

        build_tool("background_run", "Run command in background.",
                   {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]},
                   lambda **kw: "Background task started (mock)"),

        build_tool("check_background", "Check background task status.",
                   {"type": "object", "properties": {"task_id": {"type": "string"}}},
                   lambda **kw: "Task status (mock)"),

        build_tool("task_create", "Create a persistent file task.",
                   {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]},
                   lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", ""))),

        build_tool("task_get", "Get task details by ID.",
                   {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
                   lambda **kw: TASK_MGR.get(kw["task_id"])),

        build_tool("task_update", "Update task status or dependencies.",
                   {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["task_id"]},
                   lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status"))),

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

        build_tool("set_objective", "Declare or update the current user objective.",
                   {"type": "object", "properties": {"objective": {"type": "string"}}, "required": ["objective"]},
                   lambda **kw: STORE.set("current_objective", kw["objective"])),
    ])


def main():
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
    _register_tools()

    # Filter by category if requested
    args = sys.argv[1:]
    if "--list" in args:
        print("Test cases:\n")
        for case in get_all_cases():
            exp_str = case["expected"]["name"] if isinstance(case["expected"], dict) else (
                [e["name"] for e in case["expected"]] if isinstance(case["expected"], list) else "NO TOOL"
            )
            print(f"  [{case['category']:<12}] {case['prompt'][:70]}")
            print(f"                     expected: {exp_str}\n")
        return

    category = None
    for cat_name in ["simple", "irrelevant", "multiple", "parallel"]:
        if f"--{cat_name}" in args:
            category = cat_name
            break

    if category:
        name_to_cases = {
            "simple": SIMPLE,
            "irrelevant": IRRELEVANT,
            "multiple": MULTIPLE,
            "parallel": PARALLEL,
        }
        cases = name_to_cases[category]
        print(f"Running {len(cases)} [{category}] cases...\n")
    else:
        cases = get_all_cases()
        print(f"Running all {len(cases)} cases...\n")

    print(f"Model: {MODEL}")
    print(f"Tools in registry: {len(registry.names())}\n")

    run_benchmark(client, registry, MODEL, cases)


if __name__ == "__main__":
    main()
