"""DashboardSnapshot — structured observability output for the Context Engine.

DashboardSnapshot is the SINGLE OUTPUT of DashboardBuilder. It aggregates
data from SelectionResult, BudgetReport, and PipelineResult into a
readable, structured format for debugging and monitoring.

This module contains ONLY data types — no aggregation logic.
Aggregation lives in dashboard.py.
"""

from dataclasses import dataclass, field
from typing import Any


# ── Token breakdown ──────────────────────────────────────────────────


@dataclass
class TokenBreakdown:
    """Per-layer token usage summary.

    system:     Total system prompt tokens (instruction + workspace + file_cache)
    conversation: Conversation tokens
    summary:    Summary tokens
    workspace:  Workspace tokens
    file_cache: File cache tokens
    total:      Grand total across all layers
    per_layer:  Raw dict of layer_name → token_count (for extensibility)
    """

    system: int = 0
    conversation: int = 0
    summary: int = 0
    workspace: int = 0
    file_cache: int = 0
    total: int = 0
    per_layer: dict[str, int] = field(default_factory=dict)

    @property
    def layers(self) -> list[dict]:
        """Return a list of {name, tokens} for display."""
        return [
            {"name": k, "tokens": v}
            for k, v in self.per_layer.items()
        ]


# ── Selection breakdown ──────────────────────────────────────────────


@dataclass
class SelectionSourceBreakdown:
    """Per-source selection stats."""

    source: str
    candidates: int = 0
    selected: int = 0
    discarded: int = 0
    tokens: int = 0


@dataclass
class SelectionBreakdown:
    """Selection pipeline statistics.

    total_candidates: Number of candidates before any filtering
    selected:         Number of candidates that passed policy
    discarded:        Number of candidates pruned by policy
    by_source:        Per-source breakdown (source_name → SelectionSourceBreakdown)
    """

    total_candidates: int = 0
    selected: int = 0
    discarded: int = 0
    by_source: dict[str, SelectionSourceBreakdown] = field(default_factory=dict)


# ── Compression breakdown ────────────────────────────────────────────


@dataclass
class StageBreakdown:
    """Per-stage compression statistics."""

    stage_name: str
    tier: int
    skipped: bool = False
    tokens_before: int = 0
    tokens_after: int = 0
    saved_tokens: int = 0
    duration_ms: float = 0.0
    summary_updated: bool = False
    error: str | None = None


@dataclass
class CompressionBreakdown:
    """Compression pipeline statistics."""

    original_tokens: int = 0
    compressed_tokens: int = 0
    saved_tokens: int = 0
    saved_percent: float = 0.0
    stages: list[StageBreakdown] = field(default_factory=list)
    active: bool = False  # Whether compression was actually executed


# ── Latency breakdown ────────────────────────────────────────────────


@dataclass
class LatencyBreakdown:
    """Pipeline timing breakdown in milliseconds."""

    total_ms: float = 0.0
    collect_ms: float = 0.0
    rank_ms: float = 0.0
    select_ms: float = 0.0
    pack_ms: float = 0.0
    compression_ms: float = 0.0

    @property
    def has_data(self) -> bool:
        """Whether any timing data was recorded."""
        return self.total_ms > 0.0


# ── DashboardSnapshot (unified output) ───────────────────────────────


@dataclass
class DashboardSnapshot:
    """Complete observability snapshot for one prompt build.

    This is the SINGLE OUTPUT of DashboardBuilder. It contains all
    metrics needed for debugging, monitoring, and display.

    Fields:
        tokens:      Per-layer token usage breakdown.
        selection:   Selection pipeline statistics (if M4 active).
        compression: Compression statistics (if M3 active).
        latency:     Pipeline timing breakdown.
        timestamp:   Time when this snapshot was created.
    """

    tokens: TokenBreakdown = field(default_factory=TokenBreakdown)
    selection: SelectionBreakdown = field(default_factory=SelectionBreakdown)
    compression: CompressionBreakdown | None = None
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to a plain dict for serialization."""
        result = {
            "timestamp": self.timestamp,
            "tokens": {
                "system": self.tokens.system,
                "conversation": self.tokens.conversation,
                "summary": self.tokens.summary,
                "workspace": self.tokens.workspace,
                "file_cache": self.tokens.file_cache,
                "total": self.tokens.total,
                "per_layer": dict(self.tokens.per_layer),
            },
            "selection": {
                "total_candidates": self.selection.total_candidates,
                "selected": self.selection.selected,
                "discarded": self.selection.discarded,
                "by_source": {
                    k: {
                        "source": v.source,
                        "candidates": v.candidates,
                        "selected": v.selected,
                        "discarded": v.discarded,
                        "tokens": v.tokens,
                    }
                    for k, v in self.selection.by_source.items()
                },
            },
            "latency": {
                "total_ms": self.latency.total_ms,
                "collect_ms": self.latency.collect_ms,
                "rank_ms": self.latency.rank_ms,
                "select_ms": self.latency.select_ms,
                "pack_ms": self.latency.pack_ms,
                "compression_ms": self.latency.compression_ms,
            },
            "metadata": dict(self.metadata),
        }

        if self.compression is not None:
            result["compression"] = {
                "original_tokens": self.compression.original_tokens,
                "compressed_tokens": self.compression.compressed_tokens,
                "saved_tokens": self.compression.saved_tokens,
                "saved_percent": self.compression.saved_percent,
                "active": self.compression.active,
                "stages": [
                    {
                        "stage_name": s.stage_name,
                        "tier": s.tier,
                        "skipped": s.skipped,
                        "tokens_before": s.tokens_before,
                        "tokens_after": s.tokens_after,
                        "saved_tokens": s.saved_tokens,
                        "duration_ms": s.duration_ms,
                        "summary_updated": s.summary_updated,
                        "error": s.error,
                    }
                    for s in self.compression.stages
                ],
            }

        return result

    def summary_line(self) -> str:
        """Return a one-line summary for logging."""
        parts = [
            f"tokens={self.tokens.total}",
            f"selection={self.selection.selected}/{self.selection.total_candidates}",
        ]
        if self.compression and self.compression.active:
            parts.append(
                f"compression={self.compression.saved_tokens} saved"
                f" ({self.compression.saved_percent:.0%})"
            )
        parts.append(f"latency={self.latency.total_ms:.1f}ms")
        return " | ".join(parts)
