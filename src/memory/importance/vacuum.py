"""VacuumPolicy — detect low-value memories and emit VACUUMED events.

After each ACCESSED event, scans active pool for entries below the
importance threshold that haven't been accessed recently enough.
Only emits VACUUMED by default; auto-archive is opt-in.
"""

import time

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.importance.config import ImportanceConfig


class VacuumPolicy:
    """Detects low-value memories and emits VACUUMED events.

    Usage:
        vacuum = VacuumPolicy(store, events, access_tracker, config)
        vacuum.start()  # subscribes to ACCESSED (runs after each retrieval)
    """

    def __init__(
        self,
        store,                # MemoryStore
        events: MemoryEventBus,
        access_tracker,       # AccessTracker (for last_access timestamps)
        config: ImportanceConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._tracker = access_tracker
        self._config = config or ImportanceConfig()

        self._unsubscribe = None
        self._last_vacuum_ts: float = 0.0

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Subscribe to ACCESSED events (runs vacuum check after each retrieval)."""
        if self._unsubscribe is not None:
            return
        self._unsubscribe = self._events.subscribe(
            MemoryEvent.ACCESSED,
            self._on_accessed,
        )

    def stop(self) -> None:
        """Unsubscribe."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @property
    def is_running(self) -> bool:
        return self._unsubscribe is not None

    # ═══════════════════════════════════════════════════════════
    # Vacuum logic
    # ═══════════════════════════════════════════════════════════

    def _on_accessed(self, payload: MemoryEventPayload) -> None:
        """Run vacuum check after each retrieval access batch.

        Throttled: only runs once per 60 seconds to avoid scanning
        the full active pool on every single access event.
        """
        now = payload.timestamp or time.time()
        if now - self._last_vacuum_ts < 60.0:
            return
        self._last_vacuum_ts = now
        self.check()

    def check(self, now: float | None = None) -> list[str]:
        """Scan active pool for entries below the vacuum threshold.

        Criteria:
          1. importance < threshold
          2. frequency == 0 (never accessed)
          3. age > min_age_days

        Args:
            now: Current time (default: time.time()).

        Returns:
            List of entry IDs that triggered vacuum.
        """
        if not self._config.vacuum_enabled:
            return []

        if now is None:
            now = time.time()

        cfg = self._config
        threshold = cfg.vacuum_importance_threshold
        min_age_seconds = cfg.vacuum_min_age_days * 86400.0

        vacuumed: list[str] = []

        for entry_id, entry in self._store.get_active().items():
            # Check importance
            if entry.score.importance >= threshold:
                continue

            # Check frequency (never accessed)
            if entry.score.frequency > 0:
                continue

            # Check age
            age = now - entry.identity.created_at
            if age < min_age_seconds:
                continue

            # Candidate found — emit VACUUMED
            vacuumed.append(entry_id.value)
            self._events.emit(MemoryEventPayload(
                event=MemoryEvent.VACUUMED,
                entry_id=entry_id.value,
                timestamp=now,
                triggered_by="vacuum_policy",
                metadata={
                    "importance": entry.score.importance,
                    "age_days": age / 86400.0,
                    "frequency": entry.score.frequency,
                },
            ))

            # Optional auto-archive
            if cfg.vacuum_auto_archive:
                try:
                    self._store.archive(entry_id)
                except Exception:
                    pass

        return vacuumed

    def stats(self) -> dict:
        return {
            "running": self.is_running,
            "vacuum_enabled": self._config.vacuum_enabled,
            "auto_archive": self._config.vacuum_auto_archive,
            "threshold": self._config.vacuum_importance_threshold,
            "min_age_days": self._config.vacuum_min_age_days,
            "last_check": self._last_vacuum_ts,
        }
