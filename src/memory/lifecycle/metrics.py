"""LifecycleMetrics — Memory OS health dashboard.

Provides aggregate statistics across all lifecycle operations.
Reads from Store + Events + M8/M9 data, never writes.
"""

from dataclasses import dataclass, field

from src.memory.types import MemoryState


@dataclass
class LifecycleMetrics:
    """Complete Memory OS health snapshot."""

    # Pool distribution
    active_count: int = 0
    warm_count: int = 0
    cold_count: int = 0
    archived_count: int = 0
    deleted_count: int = 0

    # Importance
    avg_importance: float = 0.0
    avg_freshness: float = 0.0
    avg_frequency: float = 0.0

    # Operations (cumulative, tracked by lifecycle engine)
    total_archives: int = 0
    total_restores: int = 0
    total_compressions: int = 0
    total_merges: int = 0
    total_conflicts: int = 0

    # GC
    orphans_cleaned: int = 0
    broken_refs_repaired: int = 0
    duplicates_resolved: int = 0

    # Timeline
    last_cycle_check: float = 0.0
    last_gc: float = 0.0

    @property
    def total_entries(self) -> int:
        return self.active_count + self.warm_count + self.cold_count + self.archived_count + self.deleted_count

    @property
    def active_total(self) -> int:
        """Active-pool entries (ACTIVE + WARM + COLD)."""
        return self.active_count + self.warm_count + self.cold_count

    @property
    def health_score(self) -> float:
        """Aggregate health score 0-1. Higher is better."""
        if self.total_entries == 0:
            return 1.0
        orphan_penalty = min(0.3, self.orphans_cleaned * 0.01)
        stale_penalty = min(0.2, (self.archived_count / max(1, self.total_entries)) * 0.5)
        return max(0.0, 1.0 - orphan_penalty - stale_penalty)


class LifecycleMetricsCollector:
    """Collect metrics from MemoryStore and lifecycle components.

    Usage:
        collector = LifecycleMetricsCollector(store, state_machine, archiver, compressor, gc)
        metrics = collector.collect()
    """

    def __init__(
        self,
        store,                # MemoryStore
        state_machine=None,   # LifecycleStateMachine
        archiver=None,        # ArchiveEngine
        compressor=None,      # MemoryCompressor
        gc=None,              # GarbageCollector
    ):
        self._store = store
        self._state_machine = state_machine
        self._archiver = archiver
        self._compressor = compressor
        self._gc = gc

        # Cumulative counters
        self._total_archives = 0
        self._total_restores = 0
        self._total_compressions = 0
        self._last_cycle = 0.0
        self._last_gc = 0.0

    def collect(self) -> LifecycleMetrics:
        """Collect current metrics snapshot."""
        active = self._store.get_active()
        archived = self._store.get_archived()
        deleted = self._store.get_deleted()

        # Count by state
        counts = {s: 0 for s in MemoryState}
        for entry in active.values():
            counts[entry.state] = counts.get(entry.state, 0) + 1

        m = LifecycleMetrics(
            active_count=counts.get(MemoryState.ACTIVE, 0),
            warm_count=counts.get(MemoryState.WARM, 0),
            cold_count=counts.get(MemoryState.COLD, 0),
            archived_count=len(archived),
            deleted_count=len(deleted),
        )

        # Averages
        all_active = list(active.values())
        if all_active:
            m.avg_importance = sum(e.score.importance for e in all_active) / len(all_active)
            m.avg_freshness = sum(e.score.freshness for e in all_active) / len(all_active)
            m.avg_frequency = sum(e.score.frequency for e in all_active) / len(all_active)

        # Cumulative
        m.total_archives = self._total_archives
        m.total_restores = self._total_restores
        m.total_compressions = self._total_compressions
        m.last_cycle_check = self._last_cycle
        m.last_gc = self._last_gc

        return m

    def record_archive(self) -> None:
        self._total_archives += 1

    def record_restore(self) -> None:
        self._total_restores += 1

    def record_compression(self) -> None:
        self._total_compressions += 1

    def record_cycle(self) -> None:
        import time
        self._last_cycle = time.time()

    def record_gc(self) -> None:
        import time
        self._last_gc = time.time()
