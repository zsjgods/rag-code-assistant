"""Compression — policy, pipeline, summarizer, and circuit breaker for Context Engine.

M3 establishes the compression framework:
  - CompressionPolicy (when to compress)
  - CompressionPipeline + Stages (how to compress)
  - Summarizer (LLM abstraction for Tier 3)
  - CircuitBreaker (prevents repeated failures on Tier 2/3)
"""

from src.context.compression.policy import CompressionRule, OverBudgetRule, CompressionPolicy, CompressionPlan
from src.context.compression.summarizer import Summarizer, LLMSummarizer, SimpleSummarizer
from src.context.compression.pipeline import CompressionPipeline, CompressionStage, CompressionContext, StageResult, PipelineResult
from src.context.compression.stages import MicroCompactStage, ContextCollapseStage, AutoCompactStage
from src.context.compression.circuit_breaker import CircuitBreaker, CircuitBreakerState

__all__ = [
    "CompressionRule",
    "OverBudgetRule",
    "CompressionPolicy",
    "CompressionPlan",
    "Summarizer",
    "LLMSummarizer",
    "SimpleSummarizer",
    "CompressionPipeline",
    "CompressionStage",
    "CompressionContext",
    "StageResult",
    "PipelineResult",
    "MicroCompactStage",
    "ContextCollapseStage",
    "AutoCompactStage",
    "CircuitBreaker",
    "CircuitBreakerState",
]
