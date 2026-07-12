"""LifecycleStateMachine — evaluate and transition memory states.

Uses StateTransitionPolicy for weighted scoring. Emits events on each
transition: WARMED (ACTIVE→WARM), COOLED (WARM→COLD), ARCHIVED, RECOVERED.

All transitions go through LifecycleManager for proper pool management.
"""

import time

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.policy import StateTransitionPolicy
from src.memory.types import MemoryEntry, MemoryState


class LifecycleStateMachine:
    """Evaluate and transition memory states based on weighted scoring.

    Does NOT move pools directly — delegates to LifecycleManager for
    ACTIVE↔ARCHIVED pool moves. WARM and COLD are state-only changes
    (stay in active pool).

    Usage:
        sm = LifecycleStateMachine(store, lifecycle_mgr, events, config)
        sm.evaluate_all()  # Scan all active entries and transition
    """

    def __init__(
        self,
        store,                  # MemoryStore
        lifecycle_manager,      # LifecycleManager (M6)
        events: MemoryEventBus,
        config: LifecycleConfig | None = None,
    ):
        self._store = store
        self._lifecycle = lifecycle_manager
        self._events = events
        self._policy = StateTransitionPolicy(config or LifecycleConfig())

        # Track last access timestamps (same companion dict pattern as M8)
        self._last_access: dict[str, float] = {}

    # ═══════════════════════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════════════════════

    def evaluate_all(self) -> dict[str, int]:
        """Scan all active-pool entries and evaluate state transitions.

        Returns counts: {"warmed": N, "cooled": N, "archived": N, "no_change": N}
        """
        counts = {"warmed": 0, "cooled": 0, "archived": 0, "no_change": 0}
        now = time.time()

        for entry_id, entry in list(self._store.get_active().items()):
            # Only evaluate ACTIVE/WARM/COLD entries (ARCHIVED/DELETED skip)
            if entry.state not in (MemoryState.ACTIVE, MemoryState.WARM, MemoryState.COLD):
                continue

            old_state = entry.state
            last_access = self._last_access.get(entry.id_str)
            days_since = ((now - last_access) / 86400.0) if last_access else (
                (now - entry.identity.created_at) / 86400.0
            )

            new_state = self._policy.evaluate(entry, days_since)

            if new_state == old_state:
                counts["no_change"] += 1
                continue

            if old_state in (MemoryState.ACTIVE,) and new_state == MemoryState.WARM:
                self._transition(entry, MemoryState.WARM, now)
                counts["warmed"] += 1

            elif old_state in (MemoryState.ACTIVE, MemoryState.WARM) and new_state == MemoryState.COLD:
                self._transition(entry, MemoryState.COLD, now)
                counts["cooled"] += 1

            elif old_state in (MemoryState.WARM, MemoryState.COLD) and new_state == MemoryState.ARCHIVED:
                # Pool move: active → archived
                self._lifecycle.archive(entry_id)
                self._events.emit(MemoryEventPayload(
                    event=MemoryEvent.ARCHIVED,
                    entry_id=entry.id_str,
                    timestamp=now,
                    triggered_by="state_machine",
                    metadata={"from_state": old_state.value, "to_state": "archived"},
                ))
                counts["archived"] += 1

            elif old_state == MemoryState.ACTIVE and new_state == MemoryState.ARCHIVED:
                # Direct ACTIVE→ARCHIVED (very low score)
                self._lifecycle.archive(entry_id)
                self._events.emit(MemoryEventPayload(
                    event=MemoryEvent.ARCHIVED,
                    entry_id=entry.id_str,
                    timestamp=now,
                    triggered_by="state_machine",
                    metadata={"from_state": old_state.value, "to_state": "archived"},
                ))
                counts["archived"] += 1

        return counts

    def evaluate_one(self, entry: MemoryEntry) -> MemoryState:
        """Evaluate a single entry. Returns recommended state."""
        last_access = self._last_access.get(entry.id_str)
        now = time.time()
        days_since = ((now - last_access) / 86400.0) if last_access else (
            (now - entry.identity.created_at) / 86400.0
        )
        return self._policy.evaluate(entry, days_since)

    # ═══════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════

    def _transition(self, entry: MemoryEntry, new_state: MemoryState, now: float) -> None:
        """Apply a state transition (in-place, no pool move for WARM/COLD)."""
        old_state = entry.state
        entry.identity.state = new_state

        event = MemoryEvent.WARMED if new_state == MemoryState.WARM else MemoryEvent.COOLED
        self._events.emit(MemoryEventPayload(
            event=event,
            entry_id=entry.id_str,
            timestamp=now,
            triggered_by="state_machine",
            metadata={"from_state": old_state.value, "to_state": new_state.value},
        ))

    # ═══════════════════════════════════════════════════════════
    # Access tracking
    # ═══════════════════════════════════════════════════════════

    def record_access(self, entry_id: str, ts: float | None = None) -> None:
        """Record that an entry was accessed (called by M7 on retrieval)."""
        self._last_access[entry_id] = ts or time.time()

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        return {
            "tracked_accesses": len(self._last_access),
        }
