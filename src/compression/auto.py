"""Auto-compact: full conversation summarization via LLM.

The heaviest compression tier — saves the full transcript to disk,
then asks the LLM to produce a continuity summary.
Returns a minimal message list for restarting the conversation.
"""

import json
import time
from pathlib import Path
from typing import Any, Callable

from src.compression.collapse import CollapseCircuitBreaker

TRANSCRIPT_DIR = Path.cwd() / ".transcripts"


def auto_compact(
    messages: list,
    llm_call: Callable,
    transcript_dir: Path | None = None,
) -> list:
    """Full conversation summarization — most expensive, most aggressive.

    Saves transcript to disk for audit trail, then returns a single
    user message containing the summary.
    """
    td = transcript_dir or TRANSCRIPT_DIR
    td.mkdir(exist_ok=True)

    # Save transcript
    path = td / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")

    # Summarize the tail of the conversation (what fits)
    conv_text = json.dumps(messages, default=str)[-80000:]

    prompt = (
        "Summarize this conversation for continuity. Preserve:\n"
        "- All user requirements and decisions made\n"
        "- File paths modified and why\n"
        "- Current task status and next steps\n"
        "- Any errors encountered and their resolutions\n\n"
        f"{conv_text}"
    )

    try:
        response = llm_call(prompt)
    except Exception:
        response = "(compression failed — continuing with full context)"

    return [
        {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{response}"},
    ]


class CompressionPipeline:
    """Three-tier compression: micro → collapse → auto.

    Each tier is tried in order. If one doesn't free enough space,
    the next tier is invoked. A circuit breaker prevents infinite loops.
    """

    def __init__(
        self,
        llm_call: Callable,
        token_threshold: int = 100000,
        keep_recent: int = 3,
        collapse_head: int = 3,
        collapse_tail: int = 3,
    ):
        self.llm_call = llm_call
        self.token_threshold = token_threshold
        self.keep_recent = keep_recent
        self.collapse_head = collapse_head
        self.collapse_tail = collapse_tail
        self.breaker = CollapseCircuitBreaker(max_failures=3)

    def needs_compression(self, messages: list) -> bool:
        """Check if compression is needed."""
        from src.compression.micro import estimate_tokens
        return estimate_tokens(messages) > self.token_threshold

    def compress(self, messages: list) -> list:
        """Apply progressive compression. Returns (possibly modified) messages."""
        from src.compression.micro import estimate_tokens, microcompact
        from src.compression.collapse import context_collapse

        # Tier 1: micro-compact (zero-cost)
        microcompact(messages, self.keep_recent)
        if not self.needs_compression(messages):
            self.breaker.record_success()
            return messages

        # Tier 2: context collapse (cheaper than auto)
        if not self.breaker.is_open:
            collapsed = context_collapse(
                messages, self.llm_call,
                self.collapse_head, self.collapse_tail,
            )
            if collapsed is not None:
                self.breaker.record_success()
                return collapsed

        # Tier 3: auto-compact (most expensive, last resort)
        if not self.breaker.is_open:
            try:
                result = auto_compact(messages, self.llm_call)
                self.breaker.record_success()
                return result
            except Exception:
                self.breaker.record_failure()

        # All tiers failed or fused — return as-is
        return messages
