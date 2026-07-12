"""Built-in compression stages for the CompressionPipeline.

Three tiers:
  Tier 1 — MicroCompactStage:   zero-cost cleanup of old tool results
  Tier 2 — ContextCollapseStage: LLM-based middle-round summarization
  Tier 3 — AutoCompactStage:     full summarization → update SummaryLayer
"""

import time

from src.context.compression.pipeline import CompressionStage, CompressionContext, StageResult
from src.context.compression.summarizer import Summarizer


def _estimate(msg: list) -> int:
    """Shortcut for token estimation."""
    from src.compression.micro import estimate_tokens
    return estimate_tokens(msg)


# ── Tier 1: MicroCompactStage ───────────────────────────────────────────


class MicroCompactStage(CompressionStage):
    """Zero-cost cleanup of old tool results.

    Clears large tool_result content from older turns.
    Never calls LLM. Never updates SummaryLayer.
    """

    tier = 1

    def __init__(self, keep_recent: int = 3):
        self._keep_recent = keep_recent

    @property
    def name(self) -> str:
        return "microcompact"

    def can_run(self, ctx: CompressionContext) -> bool:
        return ctx.plan.max_tier >= 1

    def run(self, ctx: CompressionContext) -> StageResult:
        from src.compression.micro import microcompact

        before_tokens = _estimate(ctx.conversation_messages)
        before_msgs = len(ctx.conversation_messages)
        start = time.perf_counter()

        microcompact(ctx.conversation_messages, self._keep_recent)

        after_tokens = _estimate(ctx.conversation_messages)
        after_msgs = len(ctx.conversation_messages)

        if after_tokens <= ctx.plan.target_tokens:
            ctx.is_resolved = True

        return StageResult(
            stage_name=self.name,
            tier=self.tier,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            messages_before=before_msgs,
            messages_after=after_msgs,
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ── Tier 2: ContextCollapseStage ────────────────────────────────────────


class ContextCollapseStage(CompressionStage):
    """Summarize middle conversation rounds via LLM.

    Wraps the existing context_collapse() function.
    Does NOT update SummaryLayer — collapses in-place.
    """

    tier = 2

    def __init__(self, keep_head: int = 3, keep_tail: int = 3):
        self._keep_head = keep_head
        self._keep_tail = keep_tail

    @property
    def name(self) -> str:
        return "context_collapse"

    def can_run(self, ctx: CompressionContext) -> bool:
        # Don't run if circuit breaker is open (LLM calls likely to fail)
        if ctx.circuit_breaker is not None and ctx.circuit_breaker.is_open:
            return False
        return (
            ctx.plan.max_tier >= 2
            and not ctx.is_resolved
            and ctx.llm_call is not None
        )

    def run(self, ctx: CompressionContext) -> StageResult:
        from src.compression.collapse import context_collapse

        before_tokens = _estimate(ctx.conversation_messages)
        before_msgs = len(ctx.conversation_messages)
        start = time.perf_counter()
        error: str | None = None

        try:
            collapsed = context_collapse(
                ctx.conversation_messages,
                ctx.llm_call,
                keep_head=self._keep_head,
                keep_tail=self._keep_tail,
            )

            if collapsed is not None:
                ctx.conversation_messages[:] = collapsed
                if ctx.circuit_breaker:
                    ctx.circuit_breaker.record_success()
            elif ctx.circuit_breaker:
                # context_collapse returned None (no compression needed) — not a failure
                pass

        except Exception as e:
            error = str(e)
            if ctx.circuit_breaker:
                ctx.circuit_breaker.record_failure()

        duration = (time.perf_counter() - start) * 1000

        after_tokens = _estimate(ctx.conversation_messages)
        after_msgs = len(ctx.conversation_messages)

        if after_tokens <= ctx.plan.target_tokens:
            ctx.is_resolved = True

        return StageResult(
            stage_name=self.name,
            tier=self.tier,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            messages_before=before_msgs,
            messages_after=after_msgs,
            duration_ms=duration,
            error=error,
        )


# ── Tier 3: AutoCompactStage ────────────────────────────────────────────


class AutoCompactStage(CompressionStage):
    """Full summarization via summarizer → update SummaryLayer.

    This is the most aggressive tier. It:
      1. Calls summarizer.summarize() with existing summary + new messages
      2. Stores the result in SummaryLayer
      3. Truncates conversation to recent N rounds

    Requires summarizer AND summary layer to be present in context.
    """

    tier = 3

    def __init__(self, keep_recent_rounds: int = 5):
        self._keep_recent_rounds = keep_recent_rounds

    @property
    def name(self) -> str:
        return "auto_compact"

    def can_run(self, ctx: CompressionContext) -> bool:
        # Don't run if circuit breaker is open (LLM call would likely fail)
        if ctx.circuit_breaker is not None and ctx.circuit_breaker.is_open:
            return False
        return (
            ctx.plan.max_tier >= 3
            and not ctx.is_resolved
            and ctx.summarizer is not None
            and ctx.summary is not None
        )

    def run(self, ctx: CompressionContext) -> StageResult:
        before_tokens = _estimate(ctx.conversation_messages)
        before_msgs = len(ctx.conversation_messages)
        start = time.perf_counter()
        error: str | None = None

        try:
            # Get existing summary
            existing = ctx.summary.get_latest()

            # Call summarizer
            new_summary = ctx.summarizer.summarize(
                messages=ctx.conversation_messages,
                existing_summary=existing.content if existing else None,
                target_tokens=ctx.plan.target_tokens // 2,
            )

            # Store in summary layer
            ctx.summary.update(new_summary, source="tier3")

            # Truncate conversation to recent rounds
            keep_count = self._keep_recent_rounds * 2  # user + assistant pairs
            msgs = ctx.conversation_messages
            if len(msgs) > keep_count:
                ctx.conversation_messages[:] = msgs[-keep_count:]

            if ctx.circuit_breaker:
                ctx.circuit_breaker.record_success()

        except Exception as e:
            error = str(e)
            if ctx.circuit_breaker:
                ctx.circuit_breaker.record_failure()

        duration = (time.perf_counter() - start) * 1000
        after_tokens = _estimate(ctx.conversation_messages)
        after_msgs = len(ctx.conversation_messages)

        ctx.is_resolved = True  # Tier 3 always marks as resolved

        return StageResult(
            stage_name=self.name,
            tier=self.tier,
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            messages_before=before_msgs,
            messages_after=after_msgs,
            summary_updated=error is None,
            duration_ms=duration,
            error=error,
        )
