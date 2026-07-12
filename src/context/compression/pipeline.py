"""CompressionPipeline — executes compression plans through composable stages.

Pipeline runs stages in order. Each stage checks can_run() and either
skips or executes. The first stage that resolves the plan stops the pipeline.

CircuitBreaker: if the breaker opens (consecutive LLM failures in T2/T3),
the pipeline skips all LLM-based stages to avoid wasting tokens.
Tier 1 (MicroCompact) is never blocked — it costs zero tokens.

Stage separation:
  - MicroCompactStage (Tier 1):   zero-cost cleanup, no LLM
  - ContextCollapseStage (Tier 2): middle-round summarization via LLM
  - AutoCompactStage (Tier 3):    full summarization → update SummaryLayer
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from src.context.compression.policy import CompressionPlan
from src.context.compression.summarizer import Summarizer
from src.context.layers.summary import SummaryLayer


# ── Context ─────────────────────────────────────────────────────────────


@dataclass
class CompressionContext:
    """Pipeline execution context — shared across all stages.

    conversation_messages: mutable list reference; stages may modify in-place
    summary:               optional SummaryLayer for Tier 3 writes
    plan:                  the CompressionPlan this pipeline is executing
    summarizer:            high-level summarizer (used by AutoCompactStage)
    llm_call:              raw LLM callable (used by ContextCollapseStage)
    circuit_breaker:       optional CircuitBreaker (T2/T3 record success/failure)
    is_resolved:           set to True by a stage that meets the target
    stage_results:         accumulated results from completed stages
    breaker_skipped:       True if the breaker blocked T2/T3 this tick
    """

    conversation_messages: list[dict]
    plan: CompressionPlan
    summary: SummaryLayer | None = None
    summarizer: Summarizer | None = None
    llm_call: Callable[[str], str] | None = None
    circuit_breaker: Any | None = None
    is_resolved: bool = False
    stage_results: list["StageResult"] = field(default_factory=list)
    breaker_skipped: bool = False


# ── StageResult / PipelineResult ───────────────────────────────────────


@dataclass
class StageResult:
    """Result of a single compression stage execution."""

    stage_name: str
    tier: int = 0
    skipped: bool = False
    tokens_before: int = 0
    tokens_after: int = 0
    messages_before: int = 0
    messages_after: int = 0
    summary_updated: bool = False
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class PipelineResult:
    """Result of the full pipeline execution."""

    stages: list[StageResult] = field(default_factory=list)
    action: str = "noop"  # "noop" | "compress"
    total_tokens_before: int = 0
    total_tokens_after: int = 0


# ── CompressionStage (ABC) ──────────────────────────────────────────────


class CompressionStage(ABC):
    """A single compression step in the pipeline.

    Subclasses define:
      - name: human-readable identifier
      - tier: compression depth (1=lightest, 3=heaviest)
      - can_run(ctx): should this stage execute?
      - run(ctx): perform compression, return StageResult
    """

    tier: int = 0

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def can_run(self, ctx: CompressionContext) -> bool:
        """Check preconditions. Return False to skip this stage."""
        ...

    @abstractmethod
    def run(self, ctx: CompressionContext) -> StageResult:
        """Execute this stage. May modify ctx.conversation_messages."""
        ...


# ── CompressionPipeline ────────────────────────────────────────────────


class CompressionPipeline:
    """Runs a sequence of CompressionStage until the plan is resolved.

    Usage:
        pipeline = CompressionPipeline(stages=[
            MicroCompactStage(keep_recent=3),
            ContextCollapseStage(),
            AutoCompactStage(),
        ])
        result = pipeline.execute(ctx)
    """

    def __init__(self, stages: list[CompressionStage]):
        self._stages = stages

    def execute(self, ctx: CompressionContext) -> PipelineResult:
        """Execute the pipeline. Stages run in order until resolved.

        If the circuit breaker is open, Tier 2 and Tier 3 stages are
        skipped (their can_run() returns False). Tier 1 always runs —
        it costs zero tokens and doesn't call the LLM.

        Returns a PipelineResult summarizing what was done.
        """
        from src.compression.micro import estimate_tokens

        # Noop plan → skip all stages immediately
        if ctx.plan.action != "compress":
            return PipelineResult(action="noop")

        # Check circuit breaker before running any LLM-dependent stage
        if ctx.circuit_breaker is not None and ctx.circuit_breaker.is_open:
            ctx.breaker_skipped = True
            # Still run Tier 1 (zero-cost, no LLM)
            # All higher tiers skip via can_run() checking breaker

        total_before = estimate_tokens(ctx.conversation_messages)
        results: list[StageResult] = []

        for stage in self._stages:
            if not stage.can_run(ctx):
                results.append(StageResult(
                    stage_name=stage.name, tier=stage.tier, skipped=True,
                ))
                continue

            result = stage.run(ctx)
            results.append(result)
            if ctx.is_resolved:
                break

        total_after = estimate_tokens(ctx.conversation_messages)
        return PipelineResult(
            stages=results,
            action="compress" if results else "noop",
            total_tokens_before=total_before,
            total_tokens_after=total_after,
        )

    @property
    def stages(self) -> list[CompressionStage]:
        """All registered stages (read-only)."""
        return list(self._stages)
