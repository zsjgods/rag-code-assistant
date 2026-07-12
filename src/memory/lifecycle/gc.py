"""GarbageCollector — Clean / Validate / Repair memory graph.

Responsibilities (ONLY these):
  - Clean orphan relations (related dict keys pointing to non-existent entries)
  - Validate broken parent/children references
  - Repair duplicate archive entries

Does NOT purge entries — that's RetentionPolicy's job.
Does NOT touch ACTIVE/WARM/COLD entries.
"""

import time
from dataclasses import dataclass

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.types import MemoryState


@dataclass
class GCResult:
    """Result of a GarbageCollector run."""
    orphans_cleaned: int = 0
    broken_refs_repaired: int = 0
    duplicates_resolved: int = 0

    @property
    def total(self) -> int:
        return self.orphans_cleaned + self.broken_refs_repaired + self.duplicates_resolved


class GarbageCollector:
    """Clean, validate, and repair the memory graph. Never purges.

    Usage:
        gc = GarbageCollector(store, events, config)
        result = gc.collect()  # Run all cleanup phases
    """

    def __init__(
        self,
        store,                  # MemoryStore
        events: MemoryEventBus,
        config: LifecycleConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._config = config or LifecycleConfig()

    def collect(self) -> GCResult:
        """Run all enabled GC phases.

        Phase 1: Clean orphan relations
        Phase 2: Validate broken parent/children refs
        Phase 3: Repair duplicate archive entries

        Never touches ACTIVE/WARM/COLD entries. Only cleans relations
        and removes garbage from ARCHIVED/DELETED pools.
        """
        if not self._config.gc_enabled:
            return GCResult()

        result = GCResult()
        now = time.time()

        # Phase 1: Clean orphan relations
        if self._config.gc_clean_orphan_relations:
            result.orphans_cleaned = self._clean_orphan_relations()

        # Phase 2: Validate broken references
        if self._config.gc_validate_broken_refs:
            result.broken_refs_repaired = self._validate_broken_refs()

        # Phase 3: Repair duplicate archives
        if self._config.gc_repair_duplicates:
            result.duplicates_resolved = self._repair_duplicates()

        # Emit GC_COMPLETED
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.GC_COMPLETED,
            entry_id="system",
            timestamp=now,
            triggered_by="gc",
            metadata={
                "orphans_cleaned": result.orphans_cleaned,
                "broken_repaired": result.broken_refs_repaired,
                "duplicates_resolved": result.duplicates_resolved,
            },
        ))

        return result

    # ═══════════════════════════════════════════════════════════
    # Phase 1: Clean orphan relations
    # ═══════════════════════════════════════════════════════════

    def _clean_orphan_relations(self) -> int:
        """Remove related dict entries that point to non-existent entries.

        Scans all active entries. For each related key, checks if the
        target entry exists in any pool. If not, removes the relation.
        """
        cleaned = 0
        all_entries = set()
        for pool in (self._store.get_active(), self._store.get_archived(), self._store.get_deleted()):
            all_entries.update(eid.value for eid in pool)

        for entry in self._store.get_active().values():
            orphans = []
            for target_id in entry.relation.related:
                if target_id not in all_entries:
                    orphans.append(target_id)
            for orphan in orphans:
                del entry.relation.related[orphan]
                cleaned += 1

            # Also clean children list
            valid_children = [c for c in entry.relation.children if c.value in all_entries]
            removed = len(entry.relation.children) - len(valid_children)
            if removed > 0:
                entry.relation.children = valid_children
                cleaned += removed

            # Clean parent ref
            if entry.relation.parent and entry.relation.parent.value not in all_entries:
                entry.relation.parent = None
                cleaned += 1

        return cleaned

    # ═══════════════════════════════════════════════════════════
    # Phase 2: Validate broken references
    # ═══════════════════════════════════════════════════════════

    def _validate_broken_refs(self) -> int:
        """Check for entries in ARCHIVED with children still in ACTIVE.
        If a parent is archived but children are active, clear the parent ref.
        """
        repaired = 0
        active_ids = {eid.value for eid in self._store.get_active()}

        for entry in self._store.get_active().values():
            if entry.relation.parent:
                parent_id = entry.relation.parent.value
                # Check if parent exists in any pool
                parent = self._store.read(entry.relation.parent)
                if parent is None:
                    entry.relation.parent = None
                    repaired += 1
                elif parent.state == MemoryState.ARCHIVED:
                    # Parent archived but child active — clear the parent link
                    # The child is still valid, just orphaned from parent
                    parent.relation.children = [
                        c for c in parent.relation.children
                        if c.value != entry.id_str
                    ]
                    entry.relation.parent = None
                    repaired += 1

        return repaired

    # ═══════════════════════════════════════════════════════════
    # Phase 3: Repair duplicate archives
    # ═══════════════════════════════════════════════════════════

    def _repair_duplicates(self) -> int:
        """Detect and merge duplicate entries in the ARCHIVED pool.

        Two archived entries are duplicates if they have the same summary
        and type. The older one is purged (only in ARCHIVED pool).
        """
        archived = self._store.get_archived()
        if len(archived) < 2:
            return 0

        resolved = 0
        entries = list(archived.values())
        seen: dict[str, MemoryID] = {}  # key = type+summary → entry_id

        for entry in entries:
            key = f"{entry.type.value}|{entry.content.summary}"
            if key in seen:
                # Duplicate found — purge the newer one
                older_id = seen[key]
                newer_id = entry.id
                older = archived.get(older_id)
                newer = entry

                if older and newer:
                    # Keep older, purge newer
                    if newer.identity.created_at > older.identity.created_at:
                        self._store.purge(newer.id)
                        resolved += 1
            else:
                seen[key] = entry.id

        return resolved

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        return {
            "enabled": self._config.gc_enabled,
            "clean_orphans": self._config.gc_clean_orphan_relations,
            "validate_broken": self._config.gc_validate_broken_refs,
            "repair_duplicates": self._config.gc_repair_duplicates,
        }
