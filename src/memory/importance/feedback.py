"""FeedbackHandler — detect and apply explicit memory feedback.

Listens to UPDATED events for changes to score.importance or score.confidence,
and adjusts success_rate via EMA (exponential moving average).

Also provides a direct feedback() method for the memory_feedback tool.
"""

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.importance.config import ImportanceConfig


class FeedbackHandler:
    """Handles explicit user/agent feedback on memory usefulness.

    Two paths:
      1. Event-driven: subscribe to UPDATED, detect score changes → update success_rate
      2. Direct: feedback(entry_id, rating) → called by memory_feedback tool

    Usage:
        handler = FeedbackHandler(store, events, config)
        handler.start()  # subscribes to UPDATED
        handler.feedback(id, "useful")  # direct call from tool
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

        # Track success: entry_id → (total_uses, successful_uses)
        self._success_tracker: dict[str, tuple[int, int]] = {}

        self._unsubscribe = None

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Subscribe to UPDATED events."""
        if self._unsubscribe is not None:
            return
        self._unsubscribe = self._events.subscribe(
            MemoryEvent.UPDATED,
            self._on_updated,
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
    # Direct feedback (called by memory_feedback tool)
    # ═══════════════════════════════════════════════════════════

    def feedback(self, entry_id: str, rating: str) -> str:
        """Apply explicit feedback to a memory entry.

        Args:
            entry_id: MemoryID value string.
            rating: One of "useful", "not_useful", "critical".

        Returns:
            A human-readable result string.
        """
        entry = self._store.read(MemoryID(entry_id))
        if entry is None:
            return f"Memory not found: {entry_id}"

        cfg = self._config
        score = entry.score

        if rating == "useful":
            old_conf = score.confidence
            score.confidence = min(1.0, score.confidence + cfg.feedback_useful_confidence_delta)
            score.success_rate = self._ema(
                score.success_rate, 1.0, cfg.feedback_useful_success_rate_alpha
            )
            self._record_success(entry_id, True)
            return (
                f"Feedback recorded: useful\n"
                f"  Confidence: {old_conf:.2f} → {score.confidence:.2f}\n"
                f"  Success rate: {score.success_rate:.2f}"
            )

        elif rating == "not_useful":
            old_imp = score.importance
            old_conf = score.confidence
            score.importance = max(0.0, score.importance + cfg.feedback_not_useful_importance_delta)
            score.confidence = max(0.0, score.confidence + cfg.feedback_not_useful_confidence_delta)
            score.success_rate = self._ema(
                score.success_rate, 0.0, cfg.feedback_useful_success_rate_alpha
            )
            self._record_success(entry_id, False)
            return (
                f"Feedback recorded: not useful\n"
                f"  Importance: {old_imp:.2f} → {score.importance:.2f}\n"
                f"  Confidence: {old_conf:.2f} → {score.confidence:.2f}"
            )

        elif rating == "critical":
            score.importance = max(score.importance, cfg.feedback_critical_importance_floor)
            score.confidence = max(score.confidence, cfg.feedback_critical_confidence_floor)
            return (
                f"Feedback recorded: critical\n"
                f"  Importance: → {score.importance:.2f} (floor: {cfg.feedback_critical_importance_floor})\n"
                f"  Confidence: → {score.confidence:.2f} (floor: {cfg.feedback_critical_confidence_floor})"
            )

        else:
            return f"Unknown rating: {rating}. Use 'useful', 'not_useful', or 'critical'."

    # ═══════════════════════════════════════════════════════════
    # Event-driven: detect manual score changes
    # ═══════════════════════════════════════════════════════════

    def _on_updated(self, payload: MemoryEventPayload) -> None:
        """Handle UPDATED event: if score fields changed, update success_rate."""
        changes = payload.changes or {}
        score_changes = {k for k in changes if k.startswith("score.")}
        if not score_changes:
            return

        entry = self._store.read(MemoryID(payload.entry_id))
        if entry is None:
            return

        # If importance or confidence was manually raised, treat as implicit positive feedback
        for field in score_changes:
            old_val, new_val = changes.get(field, ("0", "0"))
            try:
                old_f = float(old_val)
                new_f = float(new_val)
            except (ValueError, TypeError):
                continue

            if new_f > old_f:
                # Positive adjustment → boost success_rate slightly
                entry.score.success_rate = self._ema(
                    entry.score.success_rate, 0.75, self._config.feedback_useful_success_rate_alpha
                )
            elif new_f < old_f:
                # Negative adjustment → lower success_rate
                entry.score.success_rate = self._ema(
                    entry.score.success_rate, 0.25, self._config.feedback_useful_success_rate_alpha
                )

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _ema(current: float, new_value: float, alpha: float) -> float:
        """Exponential moving average."""
        return alpha * new_value + (1 - alpha) * current

    def _record_success(self, entry_id: str, successful: bool) -> None:
        """Track success/failure for stats."""
        total, successes = self._success_tracker.get(entry_id, (0, 0))
        total += 1
        if successful:
            successes += 1
        self._success_tracker[entry_id] = (total, successes)

    def stats(self) -> dict:
        return {
            "feedback_count": len(self._success_tracker),
            "running": self.is_running,
        }
