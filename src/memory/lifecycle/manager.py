"""Memory Lifecycle Manager — Archive/Delete/Recover/Purge/Snapshot.

Manages the three-pool system (Active / Archived / Deleted) independently from
MemoryStore's CRUD. Store delegates lifecycle operations to this manager.

State transitions:
    [none]  → create  → ACTIVE
    ACTIVE  → archive → ARCHIVED
    ACTIVE  → delete  → DELETED (soft)
    ARCHIVED → recover → ACTIVE
    DELETED → recover → ACTIVE
    DELETED → purge   → [permanently removed]
"""

import copy
import time
from dataclasses import dataclass, field

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.schema import SchemaLayer
from src.memory.types import MemoryEntry, MemoryState


@dataclass
class LifecycleStats:
    """Snapshot of pool sizes."""
    active: int = 0
    archived: int = 0
    deleted: int = 0
    total: int = 0


class LifecycleManager:
    """Independent manager for memory state transitions.

    Does NOT own the pools — it receives references from MemoryStore and
    operates on them. This keeps Store in control of data while Lifecycle
    owns the transition logic.
    """

    def __init__(
        self,
        active_pool: dict[MemoryID, MemoryEntry],
        archived_pool: dict[MemoryID, MemoryEntry],
        deleted_pool: dict[MemoryID, MemoryEntry],
        events: MemoryEventBus,
    ):
        self._active = active_pool
        self._archived = archived_pool
        self._deleted = deleted_pool
        self._events = events

    # ── State Transitions ──────────────────────────────────────

    def archive(self, entry_id: MemoryID) -> bool:
        """Move from Active → Archived. Returns False if not in Active."""
        entry = self._active.pop(entry_id, None)
        if entry is None:
            return False

        entry.state = MemoryState.ARCHIVED
        self._archived[entry_id] = entry

        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.ARCHIVED,
            entry_id=entry_id.value,
            entry_snapshot=self._to_snapshot(entry),
            timestamp=time.time(),
        ))
        return True

    def recover(self, entry_id: MemoryID) -> bool:
        """Move from Archived or Deleted → Active. Returns False if not found."""
        entry = self._archived.pop(entry_id, None)
        if entry is None:
            entry = self._deleted.pop(entry_id, None)
        if entry is None:
            return False

        entry.state = MemoryState.ACTIVE
        self._active[entry_id] = entry

        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.RECOVERED,
            entry_id=entry_id.value,
            entry_snapshot=self._to_snapshot(entry),
            timestamp=time.time(),
        ))
        return True

    def soft_delete(self, entry_id: MemoryID) -> bool:
        """Move from Active → Deleted (soft delete). Returns False if not in Active."""
        entry = self._active.pop(entry_id, None)
        if entry is None:
            return False

        entry.state = MemoryState.DELETED
        self._deleted[entry_id] = entry

        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.DELETED,
            entry_id=entry_id.value,
            entry_snapshot=self._to_snapshot(entry),
            timestamp=time.time(),
        ))
        return True

    def purge(self, entry_id: MemoryID) -> bool:
        """Permanently remove a Deleted entry. Irreversible. Returns False if not in Deleted."""
        entry = self._deleted.pop(entry_id, None)
        if entry is None:
            return False

        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.PURGED,
            entry_id=entry_id.value,
            timestamp=time.time(),
        ))
        return True

    # ── Snapshot (M10 Evolution placeholder) ────────────────────

    def snapshot(self) -> dict:
        """Create a full snapshot of all three pools.

        Returns a dict suitable for serialization and later restore.
        """
        return {
            "active": {k.value: self._to_snapshot(v) for k, v in self._active.items()},
            "archived": {k.value: self._to_snapshot(v) for k, v in self._archived.items()},
            "deleted": {k.value: self._to_snapshot(v) for k, v in self._deleted.items()},
            "timestamp": time.time(),
        }

    def restore_snapshot(self, snap: dict, schema: SchemaLayer) -> int:
        """Restore all pools from a snapshot. Returns count of restored entries."""
        count = 0
        for pool_key in ("active", "archived", "deleted"):
            target_pool = getattr(self, f"_{pool_key}")
            for id_str, data in snap.get(pool_key, {}).items():
                entry = schema.deserialize(data)
                target_pool[MemoryID(id_str)] = entry
                count += 1
        return count

    # ── Stats ──────────────────────────────────────────────────

    @property
    def stats(self) -> LifecycleStats:
        return LifecycleStats(
            active=len(self._active),
            archived=len(self._archived),
            deleted=len(self._deleted),
            total=len(self._active) + len(self._archived) + len(self._deleted),
        )

    # ── Helpers ────────────────────────────────────────────────

    def _to_snapshot(self, entry: MemoryEntry) -> dict | None:
        """Convert entry to a serializable dict. Returns None if SchemaLayer not available."""
        if entry is None:
            return None
        # Use SchemaLayer if available, otherwise manual conversion
        try:
            from src.memory.schema import SchemaLayer
            return SchemaLayer().serialize(entry)
        except Exception:
            return {"_type": "MemoryEntry", "id": entry.id_str}
