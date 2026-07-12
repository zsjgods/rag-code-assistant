"""ImportanceEngine — M8 facade for dynamic memory scoring.

Assembles:
  - ImportanceScorer   — type_weight × source_weight + sigmoid boost
  - FreshnessDecay     — lazy + event-driven exponential decay
  - AccessTracker      — subscribe ACCESSED → update frequency/freshness/importance
  - FeedbackHandler    — explicit feedback → update confidence/success_rate
  - VacuumPolicy       — low-value detection → VACUUMED

Usage:
    engine = ImportanceEngine(store, events, config)
    engine.start()       # Subscribe to events
    engine.feedback(id, "useful")
    engine.stats()
    engine.stop()        # Unsubscribe
"""

import time

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.importance.config import ImportanceConfig
from src.memory.importance.decay import FreshnessDecay
from src.memory.importance.feedback import FeedbackHandler
from src.memory.importance.scoring import ImportanceScorer
from src.memory.importance.tracking import AccessTracker
from src.memory.importance.vacuum import VacuumPolicy


class ImportanceEngine:
    """M8 Importance Engine — dynamic memory scoring.

    Wires together scoring, decay, access tracking, feedback, and vacuum.
    All components communicate via MemoryEventBus — no direct coupling
    between them.

    Usage:
        engine = ImportanceEngine(store, events)
        engine.start()
        # ... memories are created, retrieved, feedback given ...
        engine.stats()
        engine.stop()
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

        # ── Components ──
        self.scorer = ImportanceScorer(self._config)
        self.decay = FreshnessDecay(self._config)
        self.tracker = AccessTracker(self._store, self._events, self._config)
        self.feedback_handler = FeedbackHandler(self._store, self._events, self._config)

        # VacuumPolicy needs the tracker for last_access timestamps
        self.vacuum = VacuumPolicy(
            self._store, self._events, self.tracker, self._config
        )

        # ── CREATED event subscription (for auto-scoring) ──
        self._unsubscribe_created = None

        self._started = False

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Start all components: subscribe to events.

        Idempotent — calling start() multiple times is safe.
        """
        if self._started:
            return

        # Start all sub-components
        self.tracker.start()
        self.feedback_handler.start()
        self.vacuum.start()

        # Subscribe to CREATED for auto-scoring
        self._unsubscribe_created = self._events.subscribe(
            MemoryEvent.CREATED,
            self._on_created,
        )

        self._started = True

        # Score all existing active entries (catch-up)
        self._score_existing()

    def stop(self) -> None:
        """Stop all components: unsubscribe from events."""
        self.tracker.stop()
        self.feedback_handler.stop()
        self.vacuum.stop()

        if self._unsubscribe_created is not None:
            self._unsubscribe_created()
            self._unsubscribe_created = None

        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    # ═══════════════════════════════════════════════════════════
    # Direct API
    # ═══════════════════════════════════════════════════════════

    def feedback(self, entry_id: str, rating: str) -> str:
        """Give explicit feedback on a memory. Delegates to FeedbackHandler.

        Args:
            entry_id: MemoryID value.
            rating: "useful", "not_useful", or "critical".

        Returns:
            Human-readable result.
        """
        result = self.feedback_handler.feedback(entry_id, rating)
        # Persist after feedback
        try:
            self._store.save()
        except Exception:
            pass
        return result

    def get_score(self, entry_id: str) -> dict | None:
        """Get effective score for a memory entry.

        Returns dict with importance, confidence, freshness (effective),
        frequency, success_rate, or None if not found.
        """
        entry = self._store.read(MemoryID(entry_id))
        if entry is None:
            return None

        effective_freshness = self.tracker.get_effective_freshness(entry_id)

        return {
            "id": entry_id,
            "importance": entry.score.importance,
            "confidence": entry.score.confidence,
            "freshness_stored": entry.score.freshness,
            "freshness_effective": effective_freshness,
            "frequency": entry.score.frequency,
            "success_rate": entry.score.success_rate,
            "type": entry.type.value,
            "source": entry.content.source,
        }

    def decay_all(self) -> int:
        """Apply lazy decay to all active entries. Returns count of decayed entries."""
        count = 0
        now = time.time()
        for entry_id, entry in self._store.get_active().items():
            last_ts = self.tracker.get_last_access(entry.id_str)
            old = entry.score.freshness
            self.decay.apply(entry.score, last_access_ts=last_ts, now=now)
            if entry.score.freshness < old:
                count += 1
        return count

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """Return aggregate stats across all components."""
        # Score distribution
        active = self._store.get_active()
        scores = [e.score.importance for e in active.values()]
        n = len(scores)
        return {
            "total_active": n,
            "importance_distribution": {
                "min": min(scores) if scores else 0.0,
                "max": max(scores) if scores else 0.0,
                "avg": sum(scores) / n if n else 0.0,
            },
            "tracker": self.tracker.stats(),
            "feedback": self.feedback_handler.stats(),
            "vacuum": self.vacuum.stats(),
            "running": self.is_running,
        }

    # ═══════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════

    def _on_created(self, payload: MemoryEventPayload) -> None:
        """Auto-score newly created entries based on type × source."""
        if not self._config.override_on_create:
            return

        entry = self._store.read(MemoryID(payload.entry_id))
        if entry is None:
            return

        if not self.scorer.should_override(entry):
            return

        base_importance = self.scorer.compute_base(entry)
        entry.score.importance = base_importance

    def _score_existing(self) -> int:
        """Catch-up: score all existing active entries that still have default importance."""
        count = 0
        for entry in self._store.get_active().values():
            if self.scorer.should_override(entry):
                base = self.scorer.compute_base(entry)
                entry.score.importance = base
                count += 1
        return count
