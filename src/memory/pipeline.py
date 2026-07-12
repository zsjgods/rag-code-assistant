"""Memory Pipeline — pluggable processing pipeline for inbound memory entries.

Stages are dynamically registered and executed in priority order. Each stage
receives the entry plus the Store reference (for context like existing entries).

Built-in stages:
  - SchemaStage:         Validate entry against schema
  - NormalizeStage:      Normalize tags, trim text, truncate summary
  - DeduplicateStage:    SHA256 exact duplicate detection
  - PolicyCheckStage:    Run MemoryPolicy rules
  - PersistStage:        Write to MemoryStore

Custom stages: subclass PipelineStage and register via pipeline.register_stage().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.memory.identity import MemoryID
from src.memory.schema import SchemaLayer
from src.memory.types import MemoryEntry


# ═══════════════════════════════════════════════════════════════════
# PipelineStage ABC
# ═══════════════════════════════════════════════════════════════════

class PipelineStage(ABC):
    """Abstract pipeline stage. Each stage transforms or validates an entry."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique stage name (e.g. 'schema', 'normalize', 'deduplicate')."""
        ...

    @abstractmethod
    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        """Process an entry.

        Args:
            entry: The memory entry (may be mutated).
            store: The MemoryStore instance (for context, lookups).

        Returns:
            (accepted: bool, reason: str, entry: MemoryEntry)
            If accepted=False, the entry is rejected and not written to store.
            The returned entry may differ from the input (e.g. after normalize).
        """
        ...

    def priority(self) -> int:
        """Lower = runs earlier. Default 50."""
        return 50


# ═══════════════════════════════════════════════════════════════════
# Built-in Stages
# ═══════════════════════════════════════════════════════════════════

class SchemaStage(PipelineStage):
    """Validate entry against SchemaLayer."""

    name = "schema"

    def __init__(self, schema: SchemaLayer | None = None):
        self._schema = schema or SchemaLayer()

    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        result = self._schema.validate(entry)
        if not result.is_valid:
            return False, f"Schema validation failed: {'; '.join(result.errors)}", entry
        return True, "ok", entry

    def priority(self) -> int:
        return 10


class NormalizeStage(PipelineStage):
    """Normalize entry fields: lowercase tags, trim text, truncate summary."""

    name = "normalize"

    def __init__(self, max_summary_length: int = 200):
        self._max_summary = max_summary_length

    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        # Normalize tags: lowercase, strip whitespace, deduplicate
        seen = set()
        normalized_tags = []
        for tag in entry.content.tags:
            t = tag.strip().lower()
            if t and t not in seen:
                seen.add(t)
                normalized_tags.append(t)
        entry.content.tags = normalized_tags

        # Trim text
        entry.content.text = entry.content.text.strip()

        # Truncate summary
        if len(entry.content.summary) > self._max_summary:
            entry.content.summary = entry.content.summary[:self._max_summary - 3] + "..."

        # Auto-generate summary if empty
        if not entry.content.summary and entry.content.text:
            text = entry.content.text
            # First non-empty line, truncated
            first_line = text.split("\n")[0].strip()
            if len(first_line) > self._max_summary:
                first_line = first_line[:self._max_summary - 3] + "..."
            entry.content.summary = first_line

        return True, "ok", entry

    def priority(self) -> int:
        return 20


class DeduplicateStage(PipelineStage):
    """Detect exact duplicates by SHA256 hash of content text.

    If an existing active entry has the same hash, this stage:
      - Increments the existing entry's frequency
      - Resets its freshness to 1.0
      - Returns the EXISTING entry (discarding the new one)
    """

    name = "deduplicate"

    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        content_hash = entry.content.hash

        # Check active pool for hash match
        for existing in store.get_active().values():
            if existing.content.hash == content_hash:
                # Merge: bump frequency, reset freshness
                existing.score.frequency += 1
                existing.score.freshness = 1.0
                # Add any new tags
                for tag in entry.content.tags:
                    if tag not in existing.content.tags:
                        existing.content.tags.append(tag)
                return True, f"Merged with existing entry {existing.id_str}", existing

        return True, "ok", entry

    def priority(self) -> int:
        return 30


class PolicyCheckStage(PipelineStage):
    """Run entry through PolicyEngine rules."""

    name = "policy_check"

    def __init__(self, policy_engine=None):
        self._engine = policy_engine  # Set at pipeline construction time

    def set_engine(self, engine) -> None:
        self._engine = engine

    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        if self._engine is None:
            return True, "ok (no policy engine configured)", entry

        # Build context for policy rules
        context = {
            "type_counts": store.stats().get("by_type", {}),
            "scope_counts": self._count_by_scope(store),
        }

        allowed, reason, blocked = self._engine.check(entry, context)
        if not allowed:
            return False, f"Policy blocked ({', '.join(blocked)}): {reason}", entry
        return True, "ok", entry

    def priority(self) -> int:
        return 40

    @staticmethod
    def _count_by_scope(store) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in store.get_active().values():
            key = e.scope.value
            counts[key] = counts.get(key, 0) + 1
        return counts


class PersistStage(PipelineStage):
    """Write entry to MemoryStore. Always last stage."""

    name = "persist"

    def process(self, entry: MemoryEntry, store) -> tuple[bool, str, MemoryEntry]:
        try:
            store.create(entry)
            return True, f"Created {entry.id_str}", entry
        except Exception as e:
            return False, f"Persist failed: {e}", entry

    def priority(self) -> int:
        return 100  # Always last


# ═══════════════════════════════════════════════════════════════════
# MemoryPipeline
# ═══════════════════════════════════════════════════════════════════

class MemoryPipeline:
    """Pluggable pipeline for processing inbound memory entries.

    Usage:
        pipeline = MemoryPipeline()
        pipeline.register_stage(SchemaStage(schema))
        pipeline.register_stage(NormalizeStage())
        pipeline.register_stage(DeduplicateStage(), after="normalize")
        pipeline.register_stage(PolicyCheckStage(), after="deduplicate")
        pipeline.register_stage(PersistStage())

        ok, reason, entry = pipeline.process(entry, store)
    """

    def __init__(self):
        self._stages: list[PipelineStage] = []

    def register_stage(
        self,
        stage: PipelineStage,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Register a stage, optionally positioning it relative to another stage.

        Args:
            stage: The stage to register.
            before: Place BEFORE the stage with this name.
            after: Place AFTER the stage with this name.
        """
        # Remove existing stage with same name
        self.remove_stage(stage.name)

        # Find insertion position
        if before is not None:
            idx = self._find_index(before)
            if idx >= 0:
                self._stages.insert(idx, stage)
                return

        if after is not None:
            idx = self._find_index(after)
            if idx >= 0:
                self._stages.insert(idx + 1, stage)
                return

        # Default: append, then sort by priority
        self._stages.append(stage)
        self._stages.sort(key=lambda s: s.priority())

    def remove_stage(self, name: str) -> bool:
        """Remove a stage by name. Returns True if found."""
        for i, stage in enumerate(self._stages):
            if stage.name == name:
                self._stages.pop(i)
                return True
        return False

    def get_stage(self, name: str) -> PipelineStage | None:
        """Look up a stage by name."""
        for stage in self._stages:
            if stage.name == name:
                return stage
        return None

    def list_stages(self) -> list[str]:
        """List all registered stage names in execution order."""
        return [s.name for s in self._stages]

    def process(
        self,
        entry: MemoryEntry,
        store,  # MemoryStore
    ) -> tuple[bool, str, MemoryEntry | None]:
        """Run all stages in priority order.

        Returns:
            (accepted: bool, reason: str, final_entry: MemoryEntry | None)
        """
        current = entry
        for stage in self._stages:
            accepted, reason, current = stage.process(current, store)
            if not accepted:
                return False, f"[{stage.name}] {reason}", None

        return True, "ok", current

    def _find_index(self, name: str) -> int:
        """Find the index of a stage by name. Returns -1 if not found."""
        for i, stage in enumerate(self._stages):
            if stage.name == name:
                return i
        return -1
