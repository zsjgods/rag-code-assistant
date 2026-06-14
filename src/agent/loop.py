"""Agent loop — the central execution engine with hook integration.

The loop mirrors Claude Code's query.ts structure:
  Pre-processing: microcompact → drain background → check inbox
  LLM call: system prompt + tools + messages
  Post-processing: tool execution with hook interception

Hook insertion points:
  SessionStart — once, at session init
  UserPromptSubmit — each user message, before LLM
  PreToolUse — each tool execution, can block or modify input
  PostToolUse — each tool execution, audit/post-process
  Stop — when LLM finishes, can force continue (exit code 2)
"""

import json
import time
from pathlib import Path
from typing import Callable

from src.agent.hooks import HookManager, HookInput, HookResult
from src.agent.filter_tools import filter_tools_for_agent
from src.compression.micro import microcompact, estimate_tokens
from src.compression.collapse import context_collapse, CollapseCircuitBreaker
from src.compression.auto import auto_compact
from src.tools.registry import ToolRegistry

WORKDIR = Path.cwd()


def _llm_call(messages: list, system: str, tools: list[dict], model: str, max_tokens: int = 8000, client=None):
    """Wrapper for Anthropic API call."""
    return client.messages.create(
        model=model,
        system=system,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
    )


def _build_system_prompt(
    base_prompt: str,
    skills_descriptions: str,
    additional_context: str = "",
) -> str:
    """Assemble the system prompt with injected context."""
    parts = [base_prompt]
    if skills_descriptions:
        parts.append(f"\nAvailable skills:\n{skills_descriptions}")
    if additional_context:
        parts.append(f"\n<additional-context>\n{additional_context}\n</additional-context>")
    return "\n".join(parts)


def agent_loop(
    messages: list,
    tools_registry: ToolRegistry,
    client,
    *,
    model: str,
    base_system: str = "",
    skills_descriptions: str = "",
    hook_manager: HookManager | None = None,
    token_threshold: int = 100000,
    keep_recent: int = 3,
    poll_interval: int = 5,
    bg_drain_fn: Callable[[], list] | None = None,
    inbox_check_fn: Callable[[], list] | None = None,
) -> None:
    """
    Main agent loop with hook integration.

    Args:
        messages: Conversation history (mutated in-place)
        tools_registry: Available tools
        client: Anthropic client
        model: Model ID
        base_system: Base system prompt
        skills_descriptions: Available skills text
        hook_manager: Optional hook manager (None = no hooks)
        token_threshold: Token count that triggers compression
        keep_recent: Tool results to preserve during microcompact
        bg_drain_fn: Function to drain background task notifications
        inbox_check_fn: Function to check the lead's inbox
    """
    hm = hook_manager
    rounds_without_todo = 0
    circuit_breaker = CollapseCircuitBreaker(max_failures=3)

    # ▶ SessionStart hook
    if hm:
        hm.execute("SessionStart", HookInput(
            event="SessionStart",
            session_context={"cwd": str(WORKDIR), "model": model},
        ))

    # Build initial system prompt
    system = _build_system_prompt(base_system, skills_descriptions)

    while True:
        # ── Pre-processing ──────────────────────────────
        # Tier 1: Micro-compact
        microcompact(messages, keep_recent)

        # Tier 2 + 3: Collapse + auto
        if estimate_tokens(messages) > token_threshold:
            if not circuit_breaker.is_open:
                collapsed = context_collapse(
                    messages,
                    lambda p: _llm_call(
                        [{"role": "user", "content": p}],
                        "You are a conversation summarizer.", [], model, 1000, client,
                    ).content[0].text,
                    keep_head=3, keep_tail=3,
                )
                if collapsed is not None:
                    messages[:] = collapsed
                    circuit_breaker.record_success()
                else:
                    try:
                        messages[:] = auto_compact(messages, lambda p: _llm_call(
                            [{"role": "user", "content": p}],
                            "You are a conversation summarizer.", [], model, 2000, client,
                        ).content[0].text)
                        circuit_breaker.record_success()
                    except Exception:
                        circuit_breaker.record_failure()
            else:
                pass  # Circuit breaker open, skip compression

        # Drain background notifications
        if bg_drain_fn:
            notifs = bg_drain_fn()
            if notifs:
                txt = "\n".join(
                    f"[bg:{n.get('task_id','?')}] {n.get('status','?')}: {str(n.get('result',''))[:200]}"
                    for n in notifs
                )
                messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})

        # Check lead inbox
        if inbox_check_fn:
            inbox = inbox_check_fn()
            if inbox:
                messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox)}</inbox>"})

        # ── LLM call ────────────────────────────────────
        tools = tools_registry.to_api_format()

        try:
            response = _llm_call(messages, system, tools, model, 8000, client)
        except Exception as e:
            messages.append({"role": "user", "content": f"[API Error: {e}]"})
            break

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # ▶ Stop hook — can force continue
            if hm:
                stop_result = hm.execute("Stop", HookInput(
                    event="Stop",
                    tool_result="".join(
                        b.text for b in response.content if hasattr(b, "text")
                    )[:5000],
                ))
                if stop_result.exit_code == 2:
                    messages.append({"role": "user", "content": stop_result.stderr or "Continue."})
                    continue
            return  # Natural stop

        # ── Tool execution with hooks ────────────────────
        results = []
        used_todo = False

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = dict(block.input)

            # ▶ PreToolUse hook
            if hm:
                pre_result = hm.execute("PreToolUse", HookInput(
                    event="PreToolUse",
                    tool_name=tool_name,
                    tool_input=tool_input,
                ))

                if pre_result.is_blocked:
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Blocked by hook: {pre_result.reason}",
                    })
                    continue

                if pre_result.updated_input:
                    tool_input = pre_result.updated_input

            # Execute tool
            try:
                output = tools_registry.execute(tool_name, **tool_input)
            except Exception as e:
                output = f"Error: {e}"

            print(f"> {tool_name}:")
            print(str(output)[:200])

            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output),
            })

            # ▶ PostToolUse hook
            if hm:
                hm.execute("PostToolUse", HookInput(
                    event="PostToolUse",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_result=str(output),
                ))

            if tool_name == "TodoWrite":
                used_todo = True

        # Todo nag reminder
        if not used_todo:
            rounds_without_todo += 1
        else:
            rounds_without_todo = 0

        if rounds_without_todo >= 3:
            results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        messages.append({"role": "user", "content": results})


def run_subagent(
    prompt: str,
    tools_registry: ToolRegistry,
    client,
    model: str,
    agent_type: str = "Explore",
    max_turns: int = 30,
) -> str:
    """Execute a sub-agent with filtered tools and limited turns."""
    from src.agent.filter_tools import filter_tools_for_agent, get_agent_tool_restriction

    restriction = get_agent_tool_restriction(agent_type)
    sub_tools = filter_tools_for_agent(
        {t.name: t for t in tools_registry._tools.values()},
        agent_type=agent_type,
        disallowed=restriction.get("disallowedTools"),
    )

    sub_tools_list = [t.to_api_format() for t in sub_tools.values()]
    sub_msgs = [{"role": "user", "content": prompt}]

    resp = None
    for _ in range(max_turns):
        try:
            resp = client.messages.create(
                model=model if model != "inherit" else "claude-haiku-4-5-20251001",
                messages=sub_msgs,
                tools=sub_tools_list,
                max_tokens=8000,
            )
        except Exception as e:
            return f"Subagent error: {e}"

        sub_msgs.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            break

        trs = []
        for b in resp.content:
            if b.type == "tool_use":
                tool = sub_tools.get(b.name)
                output = tool.execute(**b.input) if tool else f"Unknown: {b.name}"
                trs.append({"type": "tool_result", "tool_use_id": b.id, "content": str(output)[:50000]})

        sub_msgs.append({"role": "user", "content": trs})

    if resp:
        return "".join(b.text for b in resp.content if hasattr(b, "text")) or "(no summary)"
    return "(subagent failed)"
