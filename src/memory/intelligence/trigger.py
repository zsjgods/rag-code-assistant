"""TriggerPolicy — pure event source for M9 Intelligence Layer.

Detects conditions and emits TriggerEvents. Does NOT know who consumes them.
Extractor subscribes to TASK_END + MESSAGE_THRESHOLD.
ReflectionEngine subscribes to MEMORY_THRESHOLD + IMPORTANCE_SPIKE.

Design: TriggerPolicy has its own lightweight subscribe/emit for TriggerEvents,
separate from MemoryEventBus. This keeps trigger events within M9 and doesn't
pollute the M6 event system with transient signals.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from src.memory.importance.config import ImportanceConfig


class TriggerEvent(StrEnum):
    """Trigger events — pure signals. Consumers decide what to do."""
    TASK_END = "trigger.task_end"
    IDLE = "trigger.idle"
    MESSAGE_THRESHOLD = "trigger.message_threshold"
    MEMORY_THRESHOLD = "trigger.memory_threshold"
    IMPORTANCE_SPIKE = "trigger.importance_spike"


@dataclass
class TriggerPayload:
    """Payload delivered to trigger subscribers."""
    event: TriggerEvent
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


TriggerListener = Callable[[TriggerPayload], None]


class TriggerPolicy:
    """Pure event source. Detects conditions → emits TriggerEvents.

    Does NOT know about Extractor or ReflectionEngine.
    They subscribe independently.

    Usage:
        trigger = TriggerPolicy()
        trigger.subscribe(TriggerEvent.TASK_END, extractor.on_trigger)
        trigger.subscribe(TriggerEvent.MEMORY_THRESHOLD, reflector.on_trigger)

        # Called by agent loop each round
        trigger.on_message(text)
        trigger.on_task_end()
    """

    def __init__(self):
        self._listeners: dict[TriggerEvent, list[TriggerListener]] = {
            e: [] for e in TriggerEvent
        }
        self._message_count: int = 0
        self._memory_created_count: int = 0
        self._last_activity_ts: float = time.time()
        self._message_threshold: int = 8
        self._memory_threshold: int = 5
        self._idle_seconds: float = 300.0
        self._importance_spike: float = 0.85

    # ── Configuration ─────────────────────────────────────────

    def configure(
        self,
        message_threshold: int = 8,
        memory_threshold: int = 5,
        idle_seconds: float = 300.0,
        importance_spike: float = 0.85,
    ) -> None:
        """Configure trigger thresholds."""
        self._message_threshold = message_threshold
        self._memory_threshold = memory_threshold
        self._idle_seconds = idle_seconds
        self._importance_spike = importance_spike

    # ── Subscribe ─────────────────────────────────────────────

    def subscribe(self, event: TriggerEvent, listener: TriggerListener) -> Callable[[], None]:
        """Register a listener for a trigger event. Returns unsubscribe function."""
        self._listeners[event].append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners[event].remove(listener)
            except ValueError:
                pass

        return unsubscribe

    # ── Input methods (called by agent loop) ──────────────────

    def on_message(self, text: str = "") -> None:
        """Called by agent loop after each conversation turn."""
        self._message_count += 1
        self._last_activity_ts = time.time()

        if self._message_count >= self._message_threshold:
            self._emit(TriggerPayload(
                event=TriggerEvent.MESSAGE_THRESHOLD,
                timestamp=time.time(),
                metadata={"message_count": self._message_count},
            ))
            self._message_count = 0  # Reset counter

    def on_task_end(self) -> None:
        """Called when a task completes."""
        self._emit(TriggerPayload(
            event=TriggerEvent.TASK_END,
            timestamp=time.time(),
            metadata={"message_count": self._message_count},
        ))
        self._message_count = 0

    def on_memory_created(self, entry_importance: float = 0.5) -> None:
        """Called when a new memory entry is created (via CREATED event)."""
        self._memory_created_count += 1

        if self._memory_created_count >= self._memory_threshold:
            self._emit(TriggerPayload(
                event=TriggerEvent.MEMORY_THRESHOLD,
                timestamp=time.time(),
                metadata={"memory_count": self._memory_created_count},
            ))
            self._memory_created_count = 0

        # Check importance spike
        if entry_importance >= self._importance_spike:
            self._emit(TriggerPayload(
                event=TriggerEvent.IMPORTANCE_SPIKE,
                timestamp=time.time(),
                metadata={"importance": entry_importance},
            ))

    def check_idle(self) -> None:
        """Check if conversation has been idle (call periodically)."""
        elapsed = time.time() - self._last_activity_ts
        if elapsed >= self._idle_seconds:
            # Only emit once per idle period
            self._emit(TriggerPayload(
                event=TriggerEvent.IDLE,
                timestamp=time.time(),
                metadata={"idle_seconds": elapsed},
            ))
            self._last_activity_ts = time.time()  # Reset to avoid repeated emits

    # ── Internal ──────────────────────────────────────────────

    def _emit(self, payload: TriggerPayload) -> None:
        """Deliver event to all subscribers. Errors are suppressed."""
        for listener in self._listeners.get(payload.event, []):
            try:
                listener(payload)
            except Exception:
                pass

    def reset(self) -> None:
        """Reset all counters."""
        self._message_count = 0
        self._memory_created_count = 0
        self._last_activity_ts = time.time()
