"""ExecutionTrace — records Pipeline phase-by-phase execution details.

Trace captures what happened at each step of the Context Selection Pipeline:
  - Which Collector ran, how many candidates it produced
  - How Ranker reordered them
  - What Policy selected vs discarded
  - What Packer assembled

Trace is independent of the Pipeline — it's fed events by the caller
(Orchestrator or a wrapper). This keeps Pipeline pure.

Usage:
    trace = ExecutionTrace()

    # Record pipeline phases
    trace.record("collect", "InstructionCollector", candidates=3, tokens=500)
    trace.record("collect", "ConversationCollector", candidates=12, tokens=45000)
    trace.record("rank", "PriorityRanker", candidates=15, tokens=45500)
    trace.record("select", "BudgetSelectionPolicy",
                 detail="selected=10, discarded=5")
    trace.record("pack", "Packer", candidates=10, tokens=12000)

    # Get snapshot
    events = trace.snapshot()
    lines = trace.format()
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    """A single trace event in the pipeline execution.

    phase:     Pipeline phase ("collect" | "rank" | "select" | "pack" |
              "compression" | "build")
    source:    Component name (collector name, ranker name, etc.)
    candidates: Number of candidates at this point
    tokens:     Total tokens at this point
    duration_ms: Time spent in this phase
    detail:     Free-form human-readable detail
    timestamp:  When this event was recorded
    metadata:   Additional structured data
    """

    phase: str
    source: str = ""
    candidates: int = 0
    tokens: int = 0
    duration_ms: float = 0.0
    detail: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Phase constants (for consistent naming) ─────────────────────────

PHASE_COLLECT = "collect"
PHASE_RANK = "rank"
PHASE_SELECT = "select"
PHASE_PACK = "pack"
PHASE_COMPRESSION = "compression"
PHASE_BUILD = "build"


# ── ExecutionTrace ──────────────────────────────────────────────────


class ExecutionTrace:
    """Records and exposes pipeline execution events.

    Thread-safe for single-threaded usage (the Context Engine is
    single-threaded by design).

    The trace is append-only. Call clear() to reset.
    """

    def __init__(self):
        self._events: list[TraceEvent] = []
        self._enabled: bool = True

    # ── Recording ────────────────────────────────────────

    def record(
        self,
        phase: str,
        source: str = "",
        *,
        candidates: int = 0,
        tokens: int = 0,
        duration_ms: float = 0.0,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a trace event.

        Args:
            phase: Pipeline phase (use PHASE_* constants).
            source: Component that produced this event.
            candidates: Candidate count at this point.
            tokens: Token count at this point.
            duration_ms: Time spent in this phase (ms).
            detail: Free-form human-readable description.
            metadata: Additional structured data.
        """
        if not self._enabled:
            return

        import time as time_module

        self._events.append(TraceEvent(
            phase=phase,
            source=source,
            candidates=candidates,
            tokens=tokens,
            duration_ms=duration_ms,
            detail=detail,
            timestamp=time_module.time(),
            metadata=metadata or {},
        ))

    def record_collect(
        self, source: str, candidates: int, tokens: int,
        duration_ms: float = 0.0, detail: str = "",
    ) -> None:
        """Shorthand for recording a collect phase event."""
        self.record(PHASE_COLLECT, source,
                    candidates=candidates, tokens=tokens,
                    duration_ms=duration_ms, detail=detail)

    def record_rank(
        self, source: str, candidates: int, tokens: int,
        duration_ms: float = 0.0, detail: str = "",
    ) -> None:
        """Shorthand for recording a rank phase event."""
        self.record(PHASE_RANK, source,
                    candidates=candidates, tokens=tokens,
                    duration_ms=duration_ms, detail=detail)

    def record_select(
        self, source: str, selected: int, discarded: int,
        tokens: int = 0, duration_ms: float = 0.0,
    ) -> None:
        """Shorthand for recording a select phase event."""
        self.record(PHASE_SELECT, source,
                    candidates=selected + discarded,
                    tokens=tokens, duration_ms=duration_ms,
                    detail=f"selected={selected}, discarded={discarded}",
                    metadata={"selected": selected, "discarded": discarded})

    def record_pack(
        self, source: str, candidates: int, tokens: int,
        duration_ms: float = 0.0,
    ) -> None:
        """Shorthand for recording a pack phase event."""
        self.record(PHASE_PACK, source,
                    candidates=candidates, tokens=tokens,
                    duration_ms=duration_ms)

    # ── Access ───────────────────────────────────────────

    @property
    def events(self) -> list[TraceEvent]:
        """All recorded events (read-only)."""
        return list(self._events)

    def snapshot(self) -> list[TraceEvent]:
        """Return a snapshot of all events (same as .events)."""
        return self.events

    def filter(self, phase: str | None = None, source: str | None = None) -> list[TraceEvent]:
        """Filter events by phase and/or source."""
        result = self._events
        if phase:
            result = [e for e in result if e.phase == phase]
        if source:
            result = [e for e in result if e.source == source]
        return result

    # ── Display ──────────────────────────────────────────

    def format(self) -> str:
        """Format the trace as a human-readable string."""
        if not self._events:
            return "(empty trace)"

        lines: list[str] = []
        for e in self._events:
            phase_tag = f"[{e.phase:>12}]"
            source_info = f" {e.source}" if e.source else ""
            count_info = (
                f" — {e.candidates} candidates, {e.tokens} tokens"
                if e.candidates or e.tokens
                else ""
            )
            time_info = (
                f" ({e.duration_ms:.1f}ms)"
                if e.duration_ms > 0
                else ""
            )
            detail_info = f" — {e.detail}" if e.detail else ""
            lines.append(
                f"{phase_tag}{source_info}{count_info}{time_info}{detail_info}"
            )

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return f"ExecutionTrace({len(self._events)} events)"

    # ── Control ──────────────────────────────────────────

    def enable(self) -> None:
        """Enable tracing (default)."""
        self._enabled = True

    def disable(self) -> None:
        """Disable tracing (new events are dropped)."""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def clear(self) -> None:
        """Remove all recorded events."""
        self._events.clear()

    @property
    def event_count(self) -> int:
        """Number of recorded events."""
        return len(self._events)
