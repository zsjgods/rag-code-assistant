"""MemoryStore — pure storage layer for Memory OS.

Responsibilities (ONLY these):
  - CRUD (create, read, update, delete)
  - Three-pool management (active, archived, deleted)
  - Persistence (save/load to JSON)
  - Stats (counts per type, state, project)

Delegates to:
  - IndexManager   — maintains type/tag/project/owner/state indexes
  - LifecycleManager — state transitions (archive, recover, delete, purge)
  - EventBus       — emits events on all mutations

Does NOT:
  - Query, search, or rank entries (→ M7 Retrieval)
  - Validate or normalize (→ Pipeline)
  - Learn or reflect (→ M8, M9)
"""

import json
import time
from pathlib import Path

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.index import (
    IndexManager,
    OwnerIndex,
    ProjectIndex,
    StateIndex,
    TagIndex,
    TypeIndex,
)
from src.memory.lifecycle.manager import LifecycleManager
from src.memory.schema import SchemaLayer
from src.memory.types import MemoryEntry, MemoryState, MemoryType


class MemoryStore:
    """Pure storage. CRUD + 3-pool + persistence. No query/search/rank."""

    def __init__(
        self,
        db_path: Path,
        schema: SchemaLayer | None = None,
        events: MemoryEventBus | None = None,
    ):
        self._db_path = Path(db_path)
        self._schema = schema or SchemaLayer()
        self._events = events or MemoryEventBus()

        # ── Three pools ──
        self._active: dict[MemoryID, MemoryEntry] = {}
        self._archived: dict[MemoryID, MemoryEntry] = {}
        self._deleted: dict[MemoryID, MemoryEntry] = {}

        # ── Index manager ──
        self._index = IndexManager()
        self._register_default_indexes()

        # ── Lifecycle manager ──
        self._lifecycle = LifecycleManager(
            active_pool=self._active,
            archived_pool=self._archived,
            deleted_pool=self._deleted,
            events=self._events,
        )

        # Ensure db directory exists
        self._db_path.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════════════════════

    def create(self, entry: MemoryEntry) -> MemoryID:
        """Add a new entry to the active pool.

        Schema validation is the caller's responsibility (done by Pipeline).
        This method is a pure write operation.

        Returns:
            The entry's MemoryID.
        """
        entry.identity.state = MemoryState.ACTIVE

        # Ensure id is set
        if not entry.identity.id or not entry.identity.id.value:
            from uuid import uuid4
            entry.identity.id = MemoryID(uuid4().hex)

        # Ensure timestamps
        if entry.identity.created_at == 0.0:
            entry.identity.created_at = time.time()

        self._active[entry.id] = entry

        # Notify indexes
        self._index.notify_create(entry)

        # Emit event
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.CREATED,
            entry_id=entry.id_str,
            entry_snapshot=self._schema.serialize(entry),
            timestamp=time.time(),
        ))

        return entry.id

    def read(self, entry_id: MemoryID) -> MemoryEntry | None:
        """Read an entry from any pool (active, archived, or deleted).

        This is a pure lookup — no side effects.
        """
        for pool in (self._active, self._archived, self._deleted):
            entry = pool.get(entry_id)
            if entry is not None:
                return entry
        return None

    def update(self, entry_id: MemoryID, **fields) -> bool:
        """Update specific fields of an active entry.

        Args:
            entry_id: The ID of the entry to update.
            **fields: Top-level field names to update.
                      Supported: "content.text", "content.summary", "content.tags",
                      "score.importance", "score.confidence", "score.freshness",
                      "score.frequency", "score.success_rate",
                      "identity.type", "identity.scope",
                      "ownership.visibility", "ownership.project".

        Returns:
            True if the entry was found and updated, False otherwise.
        """
        entry = self._active.get(entry_id)
        if entry is None:
            return False

        changes = {}
        old_snapshot = self._schema.serialize(entry)

        for key, value in fields.items():
            old_val = self._resolve_field(entry, key)
            if old_val != value:
                changes[key] = (old_val, value)
                self._set_field(entry, key, value)

        if not changes:
            return False  # No actual changes

        # Update version
        entry.version.bump(changelog=f"Updated: {', '.join(changes.keys())}")

        # Notify indexes
        self._index.notify_update(entry, changes)

        # Emit event
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.UPDATED,
            entry_id=entry_id.value,
            entry_snapshot=old_snapshot,
            changes={k: (str(v0), str(v1)) for k, (v0, v1) in changes.items()},
            timestamp=time.time(),
        ))

        return True

    def delete(self, entry_id: MemoryID) -> bool:
        """Soft-delete an active entry (Active → Deleted).

        Delegates to LifecycleManager.
        """
        result = self._lifecycle.soft_delete(entry_id)
        if result:
            self._index.notify_delete(entry_id)
        return result

    # ═══════════════════════════════════════════════════════════
    # Lifecycle (delegated to LifecycleManager)
    # ═══════════════════════════════════════════════════════════

    def archive(self, entry_id: MemoryID) -> bool:
        """Archive an active entry (Active → Archived)."""
        result = self._lifecycle.archive(entry_id)
        if result:
            self._index.notify_delete(entry_id)
        return result

    def recover(self, entry_id: MemoryID) -> bool:
        """Recover an archived or deleted entry back to Active."""
        result = self._lifecycle.recover(entry_id)
        if result:
            entry = self._active.get(entry_id)
            if entry:
                self._index.notify_create(entry)
        return result

    def purge(self, entry_id: MemoryID) -> bool:
        """Permanently delete a soft-deleted entry. Irreversible."""
        result = self._lifecycle.purge(entry_id)
        if result:
            self._index.notify_delete(entry_id)
        return result

    # ═══════════════════════════════════════════════════════════
    # Pool access (read-only, for M7 Retrieval and tools)
    # ═══════════════════════════════════════════════════════════

    def get_active(self) -> dict[MemoryID, MemoryEntry]:
        """Return the active pool dict (reference, not copy)."""
        return self._active

    def get_archived(self) -> dict[MemoryID, MemoryEntry]:
        """Return the archived pool dict."""
        return self._archived

    def get_deleted(self) -> dict[MemoryID, MemoryEntry]:
        """Return the deleted pool dict."""
        return self._deleted

    # ═══════════════════════════════════════════════════════════
    # Index access (read-only)
    # ═══════════════════════════════════════════════════════════

    @property
    def index(self) -> IndexManager:
        """Access the index manager for type/tag/project/owner lookups."""
        return self._index

    # ═══════════════════════════════════════════════════════════
    # Events access
    # ═══════════════════════════════════════════════════════════

    @property
    def events(self) -> MemoryEventBus:
        """Access the event bus for subscribing to memory events."""
        return self._events

    # ═══════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════

    @property
    def db_file(self) -> Path:
        """Path to the JSON persistence file."""
        return self._db_path / "memory.json"

    def save(self) -> None:
        """Persist all three pools to JSON."""
        data = {
            "_schema": self._schema.version,
            "_updated_at": time.time(),
            "active": [self._schema.serialize(e) for e in self._active.values()],
            "archived": [self._schema.serialize(e) for e in self._archived.values()],
            "deleted": [self._schema.serialize(e) for e in self._deleted.values()],
        }
        self.db_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> int:
        """Load all three pools from JSON. Returns total entries loaded.

        If the file doesn't exist, returns 0 with no error.
        """
        if not self.db_file.exists():
            return 0

        data = json.loads(self.db_file.read_text(encoding="utf-8"))
        count = 0

        for pool_key in ("active", "archived", "deleted"):
            target_pool = getattr(self, f"_{pool_key}")
            for entry_data in data.get(pool_key, []):
                try:
                    entry = self._schema.deserialize(entry_data)
                    target_pool[entry.id] = entry
                    # Index active entries
                    if pool_key == "active":
                        self._index.notify_create(entry)
                    count += 1
                except Exception:
                    # Best-effort: one bad entry doesn't break the whole load
                    pass

        return count

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """Return statistics about the store.

        Returns:
            dict with keys:
              - active, archived, deleted: counts per state
              - total: sum of all pools
              - by_type: {type_name: count}
              - projects: list of unique project names
        """
        by_type: dict[str, int] = {}
        projects: set[str] = set()

        for entry in self._active.values():
            tn = entry.type.value
            by_type[tn] = by_type.get(tn, 0) + 1
            projects.add(entry.project.value)

        return {
            "active": len(self._active),
            "archived": len(self._archived),
            "deleted": len(self._deleted),
            "total": len(self._active) + len(self._archived) + len(self._deleted),
            "by_type": dict(sorted(by_type.items())),
            "projects": sorted(projects),
        }

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _register_default_indexes(self) -> None:
        """Register the 5 built-in indexes."""
        self._index.register(TypeIndex())
        self._index.register(TagIndex())
        self._index.register(ProjectIndex())
        self._index.register(OwnerIndex())
        self._index.register(StateIndex())

    def _resolve_field(self, entry: MemoryEntry, key: str):
        """Resolve a dotted field path to its value.

        Supported paths:
          - "identity.type" → entry.identity.type
          - "content.text"  → entry.content.text
          - "score.importance" → entry.score.importance
          - "state"          → entry.state (convenience alias for identity.state)
          - "project"        → entry.project.value
          - "tags"           → entry.content.tags
        """
        if key == "state":
            return entry.state
        if key == "project":
            return entry.project.value
        if key == "tags":
            return entry.content.tags

        parts = key.split(".")
        obj = entry
        for part in parts:
            obj = getattr(obj, part)
        return obj

    def _set_field(self, entry: MemoryEntry, key: str, value) -> None:
        """Set a dotted field path to a value."""
        if key == "state":
            entry.identity.state = MemoryState(value)
            return
        if key == "project":
            from src.memory.identity import ProjectID
            entry.ownership.project = ProjectID(value)
            return
        if key == "tags":
            entry.content.tags = list(value)
            return
        if key == "type":
            entry.identity.type = MemoryType(value)
            return

        parts = key.split(".")
        obj = entry
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
