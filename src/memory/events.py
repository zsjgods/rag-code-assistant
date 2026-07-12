"""Memory Event Bus — lightweight publish/subscribe for Memory Core.

Events are emitted by Store, Lifecycle, Pipeline, and Index operations.
Subscribers (Learning, Reflection, Analytics, Observability) listen without
modifying core code.

This is an in-memory event bus — no persistence, no cross-process delivery.
For durable event logging, subscribe AuditLog to relevant events.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryEvent(StrEnum):
    """All memory lifecycle events."""

    # ── CRUD ──
    CREATED = "memory.created"
    UPDATED = "memory.updated"
    DELETED = "memory.deleted"

    # ── Lifecycle ──
    ARCHIVED = "memory.archived"
    RECOVERED = "memory.recovered"
    PURGED = "memory.purged"

    # ── Advanced (M8-M10) ──
    MERGED = "memory.merged"        # M9 Reflection: two entries merged
    SPLIT = "memory.split"          # M9 Reflection: one entry split
    CONFLICT = "memory.conflict"    # M9: contradictory info detected
    SUPERSEDED = "memory.superseded"  # M9: entry replaced by newer info
    SNAPSHOTTED = "memory.snapshotted"  # M10 Evolution: snapshot taken

    # ── Lifecycle (M10) ──
    WARMED = "memory.warmed"        # M10: ACTIVE → WARM
    COOLED = "memory.cooled"        # M10: WARM → COLD
    COMPRESSED = "memory.compressed"  # M10: group compressed into summary
    GC_COMPLETED = "memory.gc_completed"  # M10: garbage collection finished

    # ── Access ──
    ACCESSED = "memory.accessed"    # Retrieved by M7 or Agent
    VACUUMED = "memory.vacuumed"    # Low-value entries purged


@dataclass
class MemoryEventPayload:
    """Payload delivered to subscribers on each event."""

    event: MemoryEvent
    entry_id: str                          # MemoryID value
    entry_snapshot: dict | None = None      # Serialized entry BEFORE the operation
    changes: dict | None = None             # Changed fields (for UPDATED)
    timestamp: float = 0.0
    triggered_by: str = "system"            # "user" | "agent" | "system" | agent_id
    metadata: dict = field(default_factory=dict)


# ── Listener type ──
Listener = Callable[[MemoryEventPayload], None]


class MemoryEventBus:
    """In-memory publish/subscribe event bus.

    Usage:
        bus = MemoryEventBus()
        unsub = bus.subscribe(MemoryEvent.CREATED, lambda p: print(f"Created {p.entry_id}"))
        bus.emit(MemoryEventPayload(event=MemoryEvent.CREATED, entry_id="abc"))
        unsub()  # stop listening
    """

    def __init__(self):
        self._listeners: dict[MemoryEvent, list[Listener]] = {
            e: [] for e in MemoryEvent
        }

    def subscribe(self, event: MemoryEvent, listener: Listener) -> Callable[[], None]:
        """Register a listener for a specific event.

        Returns an unsubscribe function.
        """
        self._listeners[event].append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners[event].remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def subscribe_all(self, listener: Listener) -> Callable[[], None]:
        """Register a listener for ALL events.

        Returns an unsubscribe function.
        """
        for event in MemoryEvent:
            self._listeners[event].append(listener)

        def unsubscribe() -> None:
            for event in MemoryEvent:
                try:
                    self._listeners[event].remove(listener)
                except ValueError:
                    pass

        return unsubscribe

    def emit(self, payload: MemoryEventPayload) -> None:
        """Deliver an event to all subscribers. Errors in listeners are suppressed."""
        for listener in self._listeners.get(payload.event, []):
            try:
                listener(payload)
            except Exception:
                pass  # Best-effort: one bad listener doesn't break others

    def clear(self) -> None:
        """Remove all listeners from all events."""
        for event in MemoryEvent:
            self._listeners[event].clear()

    @property
    def listener_count(self) -> int:
        """Total number of registered listeners across all events."""
        return sum(len(lst) for lst in self._listeners.values())


# ── Global singleton (optional) ──
memory_events = MemoryEventBus()
