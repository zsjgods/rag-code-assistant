"""Micro-compact: zero-cost cleanup of old tool results.

Before each LLM call, clears large tool_result content from older turns,
keeping the most recent N results intact. Costs zero tokens.
"""

from typing import Any


def estimate_tokens(messages: list) -> int:
    """Rough token estimation: ~4 chars per token for English."""
    import json
    return len(json.dumps(messages, default=str)) // 4


def microcompact(messages: list, keep_recent: int = 3) -> None:
    """Clear old tool_result content to save context space.

    Only clears results that are > 100 chars to avoid noise.
    The most recent `keep_recent` results are always preserved.
    """
    # Find all tool_result entries
    indices: list[tuple[int, int, Any]] = []  # (msg_idx, part_idx, part)
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for j, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append((i, j, part))

    if len(indices) <= keep_recent:
        return

    # Clear all but the most recent `keep_recent`
    for msg_idx, _, part in indices[:-keep_recent]:
        content = part.get("content")
        if isinstance(content, str) and len(content) > 100:
            part["content"] = "[cleared]"
