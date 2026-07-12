"""Memory Index Manager — pluggable index system for MemoryStore.

Each index subscribes to lifecycle events (create/update/delete) and maintains
its own lookup structure. IndexManager is a registry + notification dispatcher.

Built-in indexes:
  - TypeIndex:    MemoryType → set[MemoryID]
  - TagIndex:     tag → set[MemoryID]
  - ProjectIndex: project → set[MemoryID]
  - OwnerIndex:   owner → set[MemoryID]
  - StateIndex:   MemoryState → set[MemoryID]

Future (M7+):
  - EmbeddingIndex
  - GraphIndex
  - FullTextIndex
"""

from abc import ABC, abstractmethod
from collections import defaultdict

from src.memory.identity import MemoryID
from src.memory.types import MemoryEntry, MemoryState, MemoryType


# ═══════════════════════════════════════════════════════════════════
# Index ABC
# ═══════════════════════════════════════════════════════════════════

class Index(ABC):
    """Abstract index for fast lookup of MemoryEntry subsets.

    Each Index implementation maintains its own internal data structure.
    The IndexManager calls on_create/on_update/on_delete when Store changes.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique index name (e.g. 'type', 'tag', 'project')."""
        ...

    @abstractmethod
    def on_create(self, entry: MemoryEntry) -> None:
        """Called when a new entry is added to active pool."""
        ...

    @abstractmethod
    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        """Called when an entry is updated. `changes` = {field: (old, new)}."""
        ...

    @abstractmethod
    def on_delete(self, entry_id: MemoryID) -> None:
        """Called when an entry is removed from active pool."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Reset the index to empty state."""
        ...


# ═══════════════════════════════════════════════════════════════════
# Built-in Indexes
# ═══════════════════════════════════════════════════════════════════

class TypeIndex(Index):
    """MemoryType → set[MemoryID]."""

    name = "type"

    def __init__(self):
        self._index: dict[MemoryType, set[MemoryID]] = defaultdict(set)

    def on_create(self, entry: MemoryEntry) -> None:
        self._index[entry.type].add(entry.id)

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        old_type = None
        if "type" in changes:
            old_type = MemoryType(changes["type"][0])
            self._index[old_type].discard(entry.id)
        self._index[entry.type].add(entry.id)

    def on_delete(self, entry_id: MemoryID) -> None:
        for ids in self._index.values():
            ids.discard(entry_id)

    def clear(self) -> None:
        self._index.clear()

    def get_ids(self, type: MemoryType) -> set[MemoryID]:
        return self._index.get(type, set())

    def __contains__(self, type_id_pair: tuple[MemoryType, MemoryID]) -> bool:
        t, eid = type_id_pair
        return eid in self._index.get(t, set())


class TagIndex(Index):
    """tag → set[MemoryID]."""

    name = "tag"

    def __init__(self):
        self._index: dict[str, set[MemoryID]] = defaultdict(set)

    def on_create(self, entry: MemoryEntry) -> None:
        for tag in entry.tags:
            self._index[tag.lower()].add(entry.id)

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        if "tags" in changes:
            old_tags = set(t.lower() for t in (changes["tags"][0] or []))
            new_tags = set(t.lower() for t in entry.tags)
            # Remove from old
            for tag in old_tags - new_tags:
                self._index[tag].discard(entry.id)
            # Add to new
            for tag in new_tags - old_tags:
                self._index[tag].add(entry.id)

    def on_delete(self, entry_id: MemoryID) -> None:
        for ids in self._index.values():
            ids.discard(entry_id)

    def clear(self) -> None:
        self._index.clear()

    def get_ids(self, tag: str) -> set[MemoryID]:
        return self._index.get(tag.lower(), set())

    def __contains__(self, tag: str) -> bool:
        return len(self._index.get(tag.lower(), set())) > 0


class ProjectIndex(Index):
    """project → set[MemoryID]."""

    name = "project"

    def __init__(self):
        self._index: dict[str, set[MemoryID]] = defaultdict(set)

    def on_create(self, entry: MemoryEntry) -> None:
        self._index[entry.project.value].add(entry.id)

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        if "project" in changes:
            old = changes["project"][0]
            self._index[old].discard(entry.id)
        self._index[entry.project.value].add(entry.id)

    def on_delete(self, entry_id: MemoryID) -> None:
        for ids in self._index.values():
            ids.discard(entry_id)

    def clear(self) -> None:
        self._index.clear()

    def get_ids(self, project: str) -> set[MemoryID]:
        return self._index.get(project, set())

    def list_projects(self) -> list[str]:
        return list(self._index.keys())


class OwnerIndex(Index):
    """owner → set[MemoryID]."""

    name = "owner"

    def __init__(self):
        self._index: dict[str, set[MemoryID]] = defaultdict(set)

    def on_create(self, entry: MemoryEntry) -> None:
        self._index[entry.owner.value].add(entry.id)

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        if "owner" in changes:
            old = changes["owner"][0]
            self._index[old].discard(entry.id)
        self._index[entry.owner.value].add(entry.id)

    def on_delete(self, entry_id: MemoryID) -> None:
        for ids in self._index.values():
            ids.discard(entry_id)

    def clear(self) -> None:
        self._index.clear()

    def get_ids(self, owner: str) -> set[MemoryID]:
        return self._index.get(owner, set())


class StateIndex(Index):
    """MemoryState → set[MemoryID]."""

    name = "state"

    def __init__(self):
        self._index: dict[MemoryState, set[MemoryID]] = defaultdict(set)

    def on_create(self, entry: MemoryEntry) -> None:
        self._index[entry.state].add(entry.id)

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        if "state" in changes:
            old_state = MemoryState(changes["state"][0])
            self._index[old_state].discard(entry.id)
        self._index[entry.state].add(entry.id)

    def on_delete(self, entry_id: MemoryID) -> None:
        for ids in self._index.values():
            ids.discard(entry_id)

    def clear(self) -> None:
        self._index.clear()

    def get_ids(self, state: MemoryState) -> set[MemoryID]:
        return self._index.get(state, set())

    @property
    def active_count(self) -> int:
        return len(self._index.get(MemoryState.ACTIVE, set()))

    @property
    def archived_count(self) -> int:
        return len(self._index.get(MemoryState.ARCHIVED, set()))

    @property
    def deleted_count(self) -> int:
        return len(self._index.get(MemoryState.DELETED, set()))


# ═══════════════════════════════════════════════════════════════════
# IndexManager
# ═══════════════════════════════════════════════════════════════════

class IndexManager:
    """Registry + notification dispatcher for all Index implementations.

    Usage:
        mgr = IndexManager()
        mgr.register(TypeIndex())
        mgr.register(TagIndex())
        mgr.notify_create(entry)   # propagates to all registered indexes
    """

    def __init__(self):
        self._indexes: dict[str, Index] = {}

    def register(self, index: Index) -> None:
        """Register an index. Replaces existing index with same name."""
        self._indexes[index.name] = index

    def unregister(self, name: str) -> bool:
        """Remove an index by name. Returns True if found."""
        if name in self._indexes:
            del self._indexes[name]
            return True
        return False

    def get(self, name: str) -> Index | None:
        """Look up an index by name."""
        return self._indexes.get(name)

    def list_names(self) -> list[str]:
        """List all registered index names."""
        return list(self._indexes.keys())

    # ── Notification dispatch ──

    def notify_create(self, entry: MemoryEntry) -> None:
        """Notify all indexes of a new entry."""
        for index in self._indexes.values():
            try:
                index.on_create(entry)
            except Exception:
                pass

    def notify_update(self, entry: MemoryEntry, changes: dict) -> None:
        """Notify all indexes of an updated entry."""
        for index in self._indexes.values():
            try:
                index.on_update(entry, changes)
            except Exception:
                pass

    def notify_delete(self, entry_id: MemoryID) -> None:
        """Notify all indexes of a deleted entry."""
        for index in self._indexes.values():
            try:
                index.on_delete(entry_id)
            except Exception:
                pass

    def clear(self) -> None:
        """Clear all registered indexes."""
        for index in self._indexes.values():
            index.clear()

    def __contains__(self, name: str) -> bool:
        return name in self._indexes
