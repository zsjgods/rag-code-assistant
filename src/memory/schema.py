"""Memory Schema Layer — validate, serialize, deserialize, and migrate MemoryEntry.

This is a PURE data layer. It does NOT contain business logic (that lives in Pipeline).
Schema only checks: field existence, type correctness, version compatibility.

Serialization follows the M5 pattern: every payload carries _schema + _type envelope.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import Any

from src.memory.identity import (
    AgentID,
    MemoryID,
    ProjectID,
    SessionID,
    UserID,
    WorkspaceID,
)
from src.memory.types import (
    MemoryContent,
    MemoryEntry,
    MemoryIdentity,
    MemoryOwnership,
    MemoryRelation,
    MemoryScope,
    MemoryScore,
    MemoryState,
    MemoryType,
    MemoryVersion,
    MemoryVisibility,
)

# ── Schema version ──
SCHEMA_VERSION = "1.0"


# ═══════════════════════════════════════════════════════════════════
# SchemaResult
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SchemaResult:
    """Result of schema validation."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, warnings: list[str] | None = None) -> "SchemaResult":
        return cls(is_valid=True, warnings=warnings or [])

    @classmethod
    def fail(cls, errors: list[str]) -> "SchemaResult":
        return cls(is_valid=False, errors=errors)


# ═══════════════════════════════════════════════════════════════════
# SchemaLayer
# ═══════════════════════════════════════════════════════════════════

class SchemaLayer:
    """Data model validation, serialization, deserialization, and migration.

    Validation rules (pure data, NOT business logic):
      - identity.id must be MemoryID (non-empty)
      - identity.type must be a valid MemoryType
      - identity.scope must be a valid MemoryScope
      - identity.state must be a valid MemoryState
      - content.text must be str (non-empty for ACTIVE entries)
      - ownership.project must be ProjectID (non-empty)
      - ownership.visibility must be valid MemoryVisibility
      - score values must be in [0.0, 1.0]
      - version.number must be >= 1
    """

    def __init__(self, strict: bool = False):
        self._strict = strict  # If True, warnings become errors
        self._migrations: dict[tuple[str, str], Callable[[dict], dict]] = {}

    # ── Validation ────────────────────────────────────────────

    def validate(self, entry: MemoryEntry) -> SchemaResult:
        """Validate a MemoryEntry against the schema.

        Returns SchemaResult with errors (hard failures) and warnings (soft issues).
        """
        errors: list[str] = []
        warnings: list[str] = []

        # identity.id
        if not entry.identity.id or not entry.identity.id.value:
            errors.append("identity.id is required")

        # identity.type
        if not isinstance(entry.identity.type, MemoryType):
            errors.append(f"identity.type must be MemoryType, got {type(entry.identity.type)}")

        # identity.scope
        if not isinstance(entry.identity.scope, MemoryScope):
            errors.append(f"identity.scope must be MemoryScope, got {type(entry.identity.scope)}")

        # identity.state
        if not isinstance(entry.identity.state, MemoryState):
            errors.append(f"identity.state must be MemoryState, got {type(entry.identity.state)}")

        # content.text
        if not isinstance(entry.content.text, str):
            errors.append("content.text must be str")
        elif not entry.content.text.strip() and entry.identity.state == MemoryState.ACTIVE:
            warnings.append("content.text is empty for ACTIVE entry")

        # content.summary
        if not isinstance(entry.content.summary, str):
            errors.append("content.summary must be str")

        # content.tags
        if not isinstance(entry.content.tags, list):
            errors.append("content.tags must be list")
        else:
            for i, tag in enumerate(entry.content.tags):
                if not isinstance(tag, str):
                    errors.append(f"content.tags[{i}] must be str, got {type(tag)}")

        # ownership.project
        if not entry.ownership.project or not entry.ownership.project.value:
            errors.append("ownership.project is required")

        # ownership.owner
        if not entry.ownership.owner or not entry.ownership.owner.value:
            errors.append("ownership.owner is required")

        # ownership.visibility
        if not isinstance(entry.ownership.visibility, MemoryVisibility):
            errors.append(f"ownership.visibility must be MemoryVisibility, got {type(entry.ownership.visibility)}")

        # score range checks
        for field_name in ["importance", "confidence", "freshness", "success_rate"]:
            val = getattr(entry.score, field_name)
            if not isinstance(val, (int, float)) or val < 0.0 or val > 1.0:
                errors.append(f"score.{field_name} must be float in [0.0, 1.0], got {val}")

        # score.frequency
        if not isinstance(entry.score.frequency, int) or entry.score.frequency < 0:
            errors.append(f"score.frequency must be non-negative int, got {entry.score.frequency}")

        # version.number
        if entry.version.number < 1:
            errors.append(f"version.number must be >= 1, got {entry.version.number}")

        if self._strict and warnings:
            errors.extend(warnings)
            warnings.clear()

        return SchemaResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ── Serialization ──────────────────────────────────────────

    def serialize(self, entry: MemoryEntry) -> dict:
        """Serialize a MemoryEntry to a dict with _schema + _type envelope."""
        return {
            "_schema": SCHEMA_VERSION,
            "_type": "MemoryEntry",
            "identity": {
                "id": entry.identity.id.value,
                "type": entry.identity.type.value,
                "scope": entry.identity.scope.value,
                "state": entry.identity.state.value,
                "created_by": entry.identity.created_by.value,
                "created_at": entry.identity.created_at,
            },
            "content": {
                "text": entry.content.text,
                "summary": entry.content.summary,
                "tags": entry.content.tags,
                "source": entry.content.source,
                "reason": entry.content.reason,
            },
            "ownership": {
                "project": entry.ownership.project.value,
                "owner": entry.ownership.owner.value,
                "visibility": entry.ownership.visibility.value,
                "workspace": entry.ownership.workspace.value if entry.ownership.workspace else None,
                "session": entry.ownership.session.value if entry.ownership.session else None,
            },
            "score": {
                "importance": entry.score.importance,
                "confidence": entry.score.confidence,
                "freshness": entry.score.freshness,
                "frequency": entry.score.frequency,
                "success_rate": entry.score.success_rate,
            },
            "relation": {
                "parent": entry.relation.parent.value if entry.relation.parent else None,
                "children": [c.value for c in entry.relation.children],
                "related": entry.relation.related,
            },
            "version": {
                "number": entry.version.number,
                "updated_by": entry.version.updated_by.value if entry.version.updated_by else None,
                "updated_at": entry.version.updated_at,
                "changelog": entry.version.changelog,
            },
        }

    def deserialize(self, data: dict) -> MemoryEntry:
        """Deserialize a dict (with _schema + _type envelope) back to MemoryEntry.

        Raises ValueError if _schema is unsupported or required fields are missing.
        """
        schema_ver = data.get("_schema", "unknown")
        if schema_ver != SCHEMA_VERSION:
            # Try migration
            data = self.migrate(data, schema_ver, SCHEMA_VERSION)

        ident = data.get("identity", {})
        content = data.get("content", {})
        ownership = data.get("ownership", {})
        score = data.get("score", {})
        relation = data.get("relation", {})
        version = data.get("version", {})

        entry = MemoryEntry(
            identity=MemoryIdentity(
                id=MemoryID(ident.get("id", "")),
                type=MemoryType(ident.get("type", "knowledge")),
                scope=MemoryScope(ident.get("scope", "project")),
                state=MemoryState(ident.get("state", "active")),
                created_by=AgentID(ident.get("created_by", "system")),
                created_at=ident.get("created_at", 0.0),
            ),
            content=MemoryContent(
                text=content.get("text", ""),
                summary=content.get("summary", ""),
                tags=content.get("tags", []),
                source=content.get("source", ""),
                reason=content.get("reason", ""),
            ),
            ownership=MemoryOwnership(
                project=ProjectID(ownership.get("project", "default")),
                owner=UserID(ownership.get("owner", "default")),
                visibility=MemoryVisibility(ownership.get("visibility", "private")),
                workspace=WorkspaceID(ownership["workspace"]) if ownership.get("workspace") else None,
                session=SessionID(ownership["session"]) if ownership.get("session") else None,
            ),
            score=MemoryScore(
                importance=score.get("importance", 0.5),
                confidence=score.get("confidence", 0.5),
                freshness=score.get("freshness", 1.0),
                frequency=score.get("frequency", 0),
                success_rate=score.get("success_rate", 0.5),
            ),
            relation=MemoryRelation(
                parent=MemoryID(relation["parent"]) if relation.get("parent") else None,
                children=[MemoryID(c) for c in relation.get("children", [])],
                related=relation.get("related", {}),
            ),
            version=MemoryVersion(
                number=version.get("number", 1),
                updated_by=AgentID(version["updated_by"]) if version.get("updated_by") else None,
                updated_at=version.get("updated_at", 0.0),
                changelog=version.get("changelog", ""),
            ),
        )

        return entry

    # ── Migration ──────────────────────────────────────────────

    def register_migration(
        self,
        from_version: str,
        to_version: str,
        migrate_fn: Callable[[dict], dict],
    ) -> None:
        """Register a migration step from one schema version to another.

        Example:
            schema.register_migration("1.0", "1.1", lambda d: {**d, "new_field": "default"})
        """
        key = (from_version, to_version)
        self._migrations[key] = migrate_fn

    def migrate(self, data: dict, from_version: str, to_version: str) -> dict:
        """Migrate data from one schema version to another.

        Uses BFS to find the shortest migration path. Raises ValueError if no path exists.
        """
        if from_version == to_version:
            return data

        path = self._find_path(from_version, to_version)
        if path is None:
            raise ValueError(
                f"No migration path from schema {from_version} to {to_version}"
            )

        result = dict(data)
        for i in range(len(path) - 1):
            step_key = (path[i], path[i + 1])
            migrate_fn = self._migrations[step_key]
            result = migrate_fn(result)
            result["_schema"] = path[i + 1]

        return result

    def _find_path(self, from_v: str, to_v: str) -> list[str] | None:
        """BFS shortest path through registered migrations."""
        if from_v == to_v:
            return [from_v]

        # Build adjacency
        adj: dict[str, list[str]] = {}
        for (f, t) in self._migrations:
            adj.setdefault(f, []).append(t)

        # BFS
        queue = deque([[from_v]])
        visited = {from_v}

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in adj.get(current, []):
                if neighbor == to_v:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return None

    @property
    def version(self) -> str:
        return SCHEMA_VERSION
