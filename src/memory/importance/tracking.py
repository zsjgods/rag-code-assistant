"""AccessTracker — subscribe to ACCESSED events, update MemoryScore.

On ACCESSED:
  - frequency += 1
  - freshness reset to 1.0
  - importance += sigmoid boost (diminishing returns)
  - Record last_access timestamp for lazy decay

Companion dict: MemoryID → last_access_ts (Unix timestamp).
This lives in-memory only (not persisted) — the freshness field
itself is persisted, and decay is re-computed on load.
"""

import time

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.importance.config import ImportanceConfig
from src.memory.importance.decay import FreshnessDecay
from src.memory.importance.scoring import ImportanceScorer


class AccessTracker:
    """Tracks memory accesses and updates MemoryScore fields.

    Subscribes to ACCESSED events and updates frequency, freshness,
    and importance in the Store.

    Usage:
        tracker = AccessTracker(store, events, config)
        tracker.start()  # subscribes to ACCESSED
        tracker.stop()   # unsubscribes
    """

    def __init__(
        self,
        store,                # MemoryStore
        events: MemoryEventBus,
        config: ImportanceConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._config = config or ImportanceConfig()
        self._scorer = ImportanceScorer(self._config)
        self._decay = FreshnessDecay(self._config)

        # Companion dict: MemoryID.value → last_access_ts
        self._last_access: dict[str, float] = {}

        self._unsubscribe = None

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Subscribe to ACCESSED events."""
        if self._unsubscribe is not None:
            return  # Already started
        self._unsubscribe = self._events.subscribe(
            MemoryEvent.ACCESSED,
            self._on_accessed,
        )

    def stop(self) -> None:
        """Unsubscribe from ACCESSED events."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @property
    def is_running(self) -> bool:
        return self._unsubscribe is not None

    # ═══════════════════════════════════════════════════════════
    # Access tracking
    # ═══════════════════════════════════════════════════════════

    def _on_accessed(self, payload: MemoryEventPayload) -> None:
        """Handle ACCESSED event: update frequency, freshness, importance."""
        entry_id = MemoryID(payload.entry_id)
        entry = self._store.read(entry_id)
        if entry is None:
            return

        now = payload.timestamp or time.time()

        # Apply lazy decay before resetting (capture decay since last access)
        last_ts = self._last_access.get(entry.id_str)
        self._decay.apply(entry.score, last_access_ts=last_ts, now=now)

        # Bump frequency
        entry.score.frequency += 1

        # Sigmoid boost on importance
        entry.score.importance = self._scorer.access_boost(
            entry.score.importance, n_accesses=1
        )

        # Reset freshness to 1.0
        self._decay.touch(entry.score, now=now)

        # Record access timestamp
        self._last_access[entry.id_str] = now

    # ═══════════════════════════════════════════════════════════
    # Query
    # ═══════════════════════════════════════════════════════════

    def get_last_access(self, entry_id: str) -> float | None:
        """Return the last access timestamp for an entry, or None."""
        return self._last_access.get(entry_id)

    def get_effective_freshness(self, entry_id: str) -> float:
        """Get effective freshness for an entry with lazy decay applied."""
        entry = self._store.read(MemoryID(entry_id))
        if entry is None:
            return 0.0
        last_ts = self._last_access.get(entry_id)
        return self._decay.get_effective(entry.score, last_access_ts=last_ts)

    def stats(self) -> dict:
        return {
            "tracked_entries": len(self._last_access),
            "running": self.is_running,
        }
