"""Context collapse — mid-tier compression by API round-trip grouping.

Unlike auto-compact (summarizes everything in one expensive LLM call),
collapse splits the middle section into per-round-trip groups and summarizes
each group individually. Head and tail are kept verbatim.

Key design: grouping by API round-trip (assistant -> tool_results),
NOT by user turn. This preserves the causal chain of tool calls.
"""

import json
from typing import Callable


def _group_by_roundtrip(messages: list) -> list[list]:
    """Group messages by API round-trip.

    Each group starts with an assistant message and includes all
    subsequent tool_results until the next assistant message.
    """
    groups: list[list] = []
    current: list = []

    for msg in messages:
        if msg["role"] == "assistant" and current:
            groups.append(current)
            current = []
        current.append(msg)

    if current:
        groups.append(current)

    return groups


def _summarize_group(group: list, llm_call: Callable) -> str:
    """Summarize a single round-trip group."""
    group_text = json.dumps(group, default=str)

    if len(group_text) < 2000:
        return json.dumps(group, default=str)

    prompt = (
        "Summarize this single round of agent interaction. "
        "Preserve: file paths, function names, error messages, user requirements. "
        "Drop: full file contents, verbose tool outputs.\n\n"
        f"{group_text}"
    )

    try:
        return llm_call(prompt)
    except Exception:
        return json.dumps(group, default=str)


def context_collapse(
    messages: list,
    llm_call: Callable,
    keep_head: int = 3,
    keep_tail: int = 3,
) -> list | None:
    """
    Mid-tier compression: keep head/tail verbatim, summarize middle groups.

    Returns new messages list if compression applied, None if not needed.
    """
    groups = _group_by_roundtrip(messages)

    if len(groups) <= keep_head + keep_tail + 2:
        return None

    head = groups[:keep_head]
    middle = groups[keep_head:-keep_tail]
    tail = groups[-keep_tail:]

    summaries = []
    for group in middle:
        summary = _summarize_group(group, llm_call)
        summaries.append({"role": "user", "content": f"[collapsed round]\n{summary}"})

    result = []
    for g in head:
        result.extend(g)
    result.extend(summaries)
    for g in tail:
        result.extend(g)

    return result


class CollapseCircuitBreaker:
    """Prevents infinite compression loops. Fuses after N consecutive failures."""

    def __init__(self, max_failures: int = 3):
        self.max_failures = max_failures
        self._failures: int = 0
        self._open: bool = False

    def record_success(self):
        self._failures = 0
        self._open = False

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.max_failures:
            self._open = True

    @property
    def is_open(self) -> bool:
        return self._open

    def reset(self):
        self._failures = 0
        self._open = False
