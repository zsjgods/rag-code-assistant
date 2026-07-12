"""ArchiveEngine — automatic archiving based on Policy-driven rules.

Builds on M8 VacuumPolicy but executes the actual archive (pool move).
Uses ArchivePolicy for condition evaluation.
"""

import time

from src.memory.events import MemoryEventBus
from src.memory.identity import MemoryID
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.policy import ArchivePolicy
from src.memory.types import MemoryEntry, MemoryState


class ArchiveEngine:
    """Execute archive based on ArchivePolicy rules.

    Usage:
        engine = ArchiveEngine(store, lifecycle_mgr, events, access_tracker, config)
        archived = engine.schedule()  # Scan and archive candidates
        engine.restore(entry_id)      # Restore an archived entry
    """

    def __init__(
        self,
        store,                  # MemoryStore
        lifecycle_manager,      # LifecycleManager (M6)
        events: MemoryEventBus,
        access_tracker=None,    # AccessTracker (M8) or StateMachine for timestamps
        config: LifecycleConfig | None = None,
    ):
        self._store = store
        self._lifecycle = lifecycle_manager
        self._events = events
        self._tracker = access_tracker
        self._policy = ArchivePolicy(config or LifecycleConfig())

    def schedule(self, now: float | None = None) -> list[str]:
        """Scan active pool and archive candidates. Returns list of archived IDs."""
        if not self._policy._cfg.archive_enabled:
            return []

        if now is None:
            now = time.time()

        archived: list[str] = []

        for entry_id, entry in list(self._store.get_active().items()):
            # Only archive ACTIVE/WARM/COLD entries
            if entry.state not in (MemoryState.ACTIVE, MemoryState.WARM, MemoryState.COLD):
                continue

            days_since_access = self._get_days_since_access(entry, now)
            should, reason = self._policy.should_archive(entry, days_since_access)

            if should:
                ok = self._lifecycle.archive(entry_id)
                if ok:
                    archived.append(entry_id.value)

        return archived

    def archive_one(self, entry_id: MemoryID) -> bool:
        """Manually archive a single entry."""
        return self._lifecycle.archive(entry_id)

    def restore(self, entry_id: MemoryID) -> bool:
        """Restore an archived entry back to ACTIVE."""
        return self._lifecycle.recover(entry_id)

    def _get_days_since_access(self, entry: MemoryEntry, now: float) -> float:
        """Estimate days since last access for an entry."""
        if self._tracker:
            ts = self._tracker.get_last_access(entry.id_str)
            if ts:
                return (now - ts) / 86400.0
        # Fallback: use creation time
        return (now - entry.identity.created_at) / 86400.0

    def stats(self) -> dict:
        return {
            "enabled": self._policy._cfg.archive_enabled,
            "importance_threshold": self._policy._cfg.archive_importance_threshold,
            "min_age_days": self._policy._cfg.archive_min_age_days,
        }
