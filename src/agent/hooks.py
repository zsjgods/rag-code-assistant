"""Hook system — Agent lifecycle extension points.

Implements the observer + chain-of-responsibility pattern:
- 5 lifecycle events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop
- 2 execution types: command (shell script), prompt (LLM evaluation)
- JSON response protocol: decision, updatedInput, additionalContext
- Exit code semantics: 0=pass, 2=block, other=warn
- Priority ordering: localSettings > projectSettings > userSettings
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

WORKDIR = Path.cwd()


# ── Data types ──────────────────────────────────────────────

@dataclass
class HookInput:
    """Input passed to a hook at execution time."""
    event: str
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_result: str = ""
    user_message: str = ""
    session_context: dict = field(default_factory=dict)


@dataclass
class HookResult:
    """Structured output from a hook execution."""
    decision: str = "approve"       # "approve" | "block"
    reason: str = ""
    additional_context: str = ""
    updated_input: dict | None = None
    exit_code: int = 0
    stderr: str = ""
    stdout: str = ""

    @property
    def is_blocked(self) -> bool:
        return self.exit_code == 2 or self.decision == "block"


@dataclass
class HookConfig:
    """Configuration for a single hook."""
    type: str                       # "command" | "prompt"
    matcher: str = ""               # e.g. "Bash", "Write(rm *)"
    command: str = ""               # for command type
    prompt: str = ""                # for prompt type
    timeout: int = 5000             # ms
    async_mode: bool = False
    priority: str = "project"       # local > project > user


# ── Matcher ─────────────────────────────────────────────────

def match_hook(hook: HookConfig, event: str, tool_name: str = "") -> bool:
    """Check if a hook should fire for the given event + tool."""
    if not hook.matcher:
        return True  # No matcher = match all for this event
    matcher = hook.matcher
    # Handle tool-specific matching: "Bash(rm *)" pattern
    if "(" in matcher:
        prefix = matcher[:matcher.index("(")]
        if tool_name != prefix.strip():
            return False
        return True  # Simplified: always match if tool name matches prefix
    return matcher == tool_name or matcher == "*"


# ── Execution ───────────────────────────────────────────────

def _resolve_command(cmd: str, hook_input: HookInput) -> str:
    """Replace $INPUT_JSON placeholder with actual input JSON."""
    input_json = json.dumps({
        "event": hook_input.event,
        "tool_name": hook_input.tool_name,
        "tool_input": hook_input.tool_input,
        "user_message": hook_input.user_message,
    })
    return cmd.replace("$INPUT_JSON", f"'{input_json}'")


def _parse_output(stdout: str, stderr: str, exit_code: int) -> HookResult:
    """Parse hook output — try JSON, fall back to exit-code-only."""
    result = HookResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    # Try to find JSON in stdout
    try:
        text = stdout.strip()
        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
            result.decision = data.get("decision", result.decision)
            result.reason = data.get("reason", result.reason)
            result.additional_context = data.get("additionalContext", result.additional_context)
            # Extract updatedInput from hookSpecificOutput
            hso = data.get("hookSpecificOutput", {})
            if hso.get("updatedInput"):
                result.updated_input = hso["updatedInput"]
    except (json.JSONDecodeError, KeyError):
        pass

    return result


def execute_command_hook(hook: HookConfig, hook_input: HookInput) -> HookResult:
    """Execute a command-type hook as a shell subprocess."""
    cmd = _resolve_command(hook.command, hook_input)
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=hook.timeout / 1000,
        )
        return _parse_output(r.stdout.strip(), r.stderr.strip(), r.returncode)
    except subprocess.TimeoutExpired:
        return HookResult(exit_code=1, stderr=f"Hook timed out after {hook.timeout}ms")
    except Exception as e:
        return HookResult(exit_code=1, stderr=str(e))


def execute_prompt_hook(hook: HookConfig, hook_input: HookInput, llm_call: Callable) -> HookResult:
    """Execute a prompt-type hook by calling an LLM for evaluation."""
    resolved = hook.prompt.replace(
        "$ARGUMENTS",
        json.dumps({
            "tool_name": hook_input.tool_name,
            "tool_input": hook_input.tool_input,
        }),
    )
    try:
        response = llm_call(resolved)
        return _parse_output(response, "", 0)
    except Exception as e:
        return HookResult(exit_code=1, stderr=str(e))


# ── Hook Manager ────────────────────────────────────────────

class HookManager:
    """Manages hook registration, event dispatch, and priority ordering."""

    # Priority order: lower index = higher priority
    PRIORITY_ORDER = {"local": 0, "project": 1, "user": 2}

    def __init__(self):
        self._hooks: dict[str, list[HookConfig]] = {
            "SessionStart": [],
            "UserPromptSubmit": [],
            "PreToolUse": [],
            "PostToolUse": [],
            "Stop": [],
        }
        self._disabled: bool = False
        self._llm_call: Optional[Callable] = None
        # Track hook execution for async rewake
        self._last_stop_check: dict = {}

    def register(self, event: str, hook: HookConfig) -> None:
        if event in self._hooks:
            self._hooks[event].append(hook)

    def set_llm(self, llm_call: Callable) -> None:
        self._llm_call = llm_call

    def disable_all(self):
        self._disabled = True

    def enable_all(self):
        self._disabled = False

    def load_from_config(self, config: dict) -> None:
        """Load hooks from settings.json format."""
        hooks_config = config.get("hooks", {})
        for event, matchers in hooks_config.items():
            if event not in self._hooks:
                continue
            for matcher_entry in matchers:
                matcher = matcher_entry.get("matcher", "")
                priority = matcher_entry.get("priority", "project")
                for h in matcher_entry.get("hooks", []):
                    hook = HookConfig(
                        type=h.get("type", "command"),
                        matcher=matcher,
                        command=h.get("command", ""),
                        prompt=h.get("prompt", ""),
                        timeout=h.get("timeout", 5000),
                        async_mode=h.get("async", False),
                        priority=priority,
                    )
                    self._hooks[event].append(hook)
        self._sort_by_priority()

    def _sort_by_priority(self):
        for event in self._hooks:
            self._hooks[event].sort(
                key=lambda h: self.PRIORITY_ORDER.get(h.priority, 99)
            )

    def _get_matching(self, event: str, tool_name: str = "") -> list[HookConfig]:
        if self._disabled or event not in self._hooks:
            return []
        return [h for h in self._hooks[event] if match_hook(h, event, tool_name)]

    def execute(self, event: str, hook_input: HookInput) -> HookResult:
        """Execute all matching hooks for an event. First block wins."""
        combined_result = HookResult()

        for hook in self._get_matching(event, hook_input.tool_name):
            if hook.async_mode:
                # Async hooks don't block — fire and forget
                import threading
                threading.Thread(
                    target=execute_command_hook, args=(hook, hook_input),
                    daemon=True,
                ).start()
                continue

            if hook.type == "command":
                result = execute_command_hook(hook, hook_input)
            elif hook.type == "prompt" and self._llm_call:
                result = execute_prompt_hook(hook, hook_input, self._llm_call)
            else:
                continue  # Skip unknown types

            # Merge additional context from all hooks
            if result.additional_context:
                if combined_result.additional_context:
                    combined_result.additional_context += "\n" + result.additional_context
                else:
                    combined_result.additional_context = result.additional_context

            # First block wins
            if result.is_blocked:
                combined_result.decision = "block"
                combined_result.reason = result.reason or result.stderr
                combined_result.exit_code = result.exit_code
                combined_result.updated_input = result.updated_input
                return combined_result

            # Apply updatedInput from the highest-priority hook that provides it
            if result.updated_input and not combined_result.updated_input:
                combined_result.updated_input = result.updated_input

        return combined_result


# Global singleton
hooks = HookManager()
