"""Observability — metrics, tracing, and audit for the Context Engine.

Three independent subsystems:
  DashboardBuilder → DashboardSnapshot
    Aggregates SelectionResult + BudgetReport + PipelineResult into
    a structured snapshot with token/selection/compression/latency breakdowns.

  ExecutionTrace
    Records pipeline phase-by-phase events (collect → rank → select → pack)
    for debugging "why did/didn't this context enter the prompt."

  AuditLog
    Records every pipeline build with full SelectionResult + Dashboard.
    Ring-buffer in memory, optional Store persistence.

All three are zero-state aggregation/recording tools — they don't
participate in Runtime decisions.
"""

from src.context.observability.snapshot import (
    DashboardSnapshot,
    TokenBreakdown,
    SelectionBreakdown,
    SelectionSourceBreakdown,
    CompressionBreakdown,
    StageBreakdown,
    LatencyBreakdown,
)
from src.context.observability.dashboard import DashboardBuilder
from src.context.observability.trace import (
    ExecutionTrace,
    TraceEvent,
    PHASE_COLLECT,
    PHASE_RANK,
    PHASE_SELECT,
    PHASE_PACK,
    PHASE_COMPRESSION,
    PHASE_BUILD,
)
from src.context.observability.audit import AuditLog

__all__ = [
    # Snapshot types
    "DashboardSnapshot",
    "TokenBreakdown",
    "SelectionBreakdown",
    "SelectionSourceBreakdown",
    "CompressionBreakdown",
    "StageBreakdown",
    "LatencyBreakdown",
    # Builder
    "DashboardBuilder",
    # Trace
    "ExecutionTrace",
    "TraceEvent",
    "PHASE_COLLECT",
    "PHASE_RANK",
    "PHASE_SELECT",
    "PHASE_PACK",
    "PHASE_COMPRESSION",
    "PHASE_BUILD",
    # Audit
    "AuditLog",
]
