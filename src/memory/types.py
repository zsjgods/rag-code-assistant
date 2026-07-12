"""Memory Core Types — complete data model for Memory OS.

MemoryEntry is split into 6 logical sub-structures:
    MemoryIdentity  — who/what/where/when this memory is
    MemoryContent   — the actual knowledge
    MemoryOwnership — who owns it, who can see it
    MemoryScore     — dynamic value metrics (M11)
    MemoryRelation  — graph relationships (M10)
    MemoryVersion   — version tracking (M10)

All enums (MemoryType, MemoryState, MemoryScope, MemoryVisibility) are defined here.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from src.memory.identity import (
    AgentID,
    MemoryID,
    ProjectID,
    SessionID,
    UserID,
    WorkspaceID,
)


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════

class MemoryType(StrEnum):
    """What kind of knowledge this memory represents."""
    USER = "user"              # User preferences, habits, background
    PROJECT = "project"        # Project conventions, structure
    CONVERSATION = "conversation"  # Key conclusions from conversations
    DECISION = "decision"      # Architecture / technical decisions
    EXPERIENCE = "experience"  # Lessons learned, pitfalls
    TOOL = "tool"              # Tool usage experience
    KNOWLEDGE = "knowledge"    # General domain knowledge
    CODE = "code"              # Code patterns, best practices


class MemoryState(StrEnum):
    """Lifecycle state of a memory entry."""
    ACTIVE = "active"          # Normal — participates in retrieval
    WARM = "warm"              # M10: being accessed but freshness decaying
    COLD = "cold"              # M10: long time no access, importance low
    ARCHIVED = "archived"      # Archived — not retrieved but recoverable
    DELETED = "deleted"        # Soft-deleted — recoverable


class MemoryScope(StrEnum):
    """Namespace / reach of a memory."""
    GLOBAL = "global"          # Cross-project, cross-user
    PROJECT = "project"        # Scoped to current project
    WORKSPACE = "workspace"    # Scoped to current workspace
    SESSION = "session"        # Scoped to current session (auto-archived)
    SHARED = "shared"          # Visible to specific users/groups


class MemoryVisibility(StrEnum):
    """Access control level."""
    PRIVATE = "private"        # Only the creator
    TEAM = "team"              # Same project members
    PUBLIC = "public"          # Everyone


# ═══════════════════════════════════════════════════════════════════
# MemoryEntry sub-structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemoryIdentity:
    """Who/what/where/when this memory is."""
    id: MemoryID = field(default_factory=lambda: MemoryID(uuid.uuid4().hex))
    type: MemoryType = MemoryType.KNOWLEDGE
    scope: MemoryScope = MemoryScope.PROJECT
    state: MemoryState = MemoryState.ACTIVE
    created_by: AgentID | UserID = field(default_factory=lambda: AgentID("system"))
    created_at: float = field(default_factory=time.time)

    @property
    def id_str(self) -> str:
        return self.id.value


@dataclass
class MemoryContent:
    """The actual knowledge payload."""
    text: str = ""                     # Full content (structured markdown)
    summary: str = ""                  # One-line summary for indexing
    tags: list[str] = field(default_factory=list)
    source: str = ""                   # task_id / conversation_id / "manual"
    reason: str = ""                   # Why this memory was created/updated

    @property
    def hash(self) -> str:
        """SHA256 of text content — used for deduplication."""
        import hashlib
        return hashlib.sha256(self.text.encode()).hexdigest()


@dataclass
class MemoryOwnership:
    """Who owns this memory and who can access it."""
    project: ProjectID = field(default_factory=lambda: ProjectID("default"))
    owner: UserID | AgentID = field(default_factory=lambda: UserID("default"))
    visibility: MemoryVisibility = MemoryVisibility.PRIVATE
    workspace: WorkspaceID | None = None
    session: SessionID | None = None


@dataclass
class MemoryScore:
    """Dynamic value metrics. Updated by M11 Importance engine."""
    importance: float = 0.5     # 0.0–1.0
    confidence: float = 0.5     # 0.0–1.0
    freshness: float = 1.0      # 0.0–1.0 (1 = just created, exponential decay)
    frequency: int = 0          # Times retrieved
    success_rate: float = 0.5   # 0.0–1.0

    def decay(self, half_life_days: float = 30.0, now: float | None = None) -> None:
        """Exponential decay: freshness *= 0.5^(days/half_life)."""
        # Lightweight — only decays when explicitly called
        pass  # Implemented in M11; placeholder for data model completeness


@dataclass
class MemoryRelation:
    """Graph relationships between memories (M10 Evolution)."""
    parent: MemoryID | None = None
    children: list[MemoryID] = field(default_factory=list)
    related: dict[str, str] = field(default_factory=dict)  # MemoryID.value → relation_type

    def add_child(self, child_id: MemoryID) -> None:
        if child_id not in self.children:
            self.children.append(child_id)

    def add_relation(self, target_id: MemoryID, relation_type: str) -> None:
        self.related[target_id.value] = relation_type


@dataclass
class MemoryVersion:
    """Version tracking for evolution history (M10)."""
    number: int = 1
    updated_by: AgentID | UserID | None = None
    updated_at: float = 0.0
    changelog: str = ""

    def bump(self, by: AgentID | UserID | None = None, changelog: str = "") -> None:
        self.number += 1
        self.updated_by = by
        self.updated_at = time.time()
        if changelog:
            self.changelog = changelog


# ═══════════════════════════════════════════════════════════════════
# Assembled MemoryEntry
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """A single memory — the core data unit of Memory OS.

    Split into 6 sub-structures for maintainability:
      - identity:   who/what/where/when
      - content:    the actual knowledge
      - ownership:  access control
      - score:      dynamic value metrics
      - relation:   graph links
      - version:    change tracking
    """

    identity: MemoryIdentity = field(default_factory=MemoryIdentity)
    content: MemoryContent = field(default_factory=MemoryContent)
    ownership: MemoryOwnership = field(default_factory=MemoryOwnership)
    score: MemoryScore = field(default_factory=MemoryScore)
    relation: MemoryRelation = field(default_factory=MemoryRelation)
    version: MemoryVersion = field(default_factory=MemoryVersion)

    # ── Convenience properties (delegate to sub-structures) ──

    @property
    def id(self) -> MemoryID:
        return self.identity.id

    @property
    def id_str(self) -> str:
        return self.identity.id_str

    @property
    def type(self) -> MemoryType:
        return self.identity.type

    @property
    def state(self) -> MemoryState:
        return self.identity.state

    @state.setter
    def state(self, value: MemoryState) -> None:
        self.identity.state = value

    @property
    def scope(self) -> MemoryScope:
        return self.identity.scope

    @property
    def project(self) -> ProjectID:
        return self.ownership.project

    @property
    def owner(self) -> UserID | AgentID:
        return self.ownership.owner

    @property
    def text(self) -> str:
        return self.content.text

    @property
    def summary(self) -> str:
        return self.content.summary

    @property
    def tags(self) -> list[str]:
        return self.content.tags

    @property
    def importance(self) -> float:
        return self.score.importance

    @property
    def freshness(self) -> float:
        return self.score.freshness

    @property
    def frequency(self) -> int:
        return self.score.frequency

    # ── Factory helpers ──

    @classmethod
    def create(
        cls,
        text: str,
        *,
        type: MemoryType = MemoryType.KNOWLEDGE,
        summary: str = "",
        tags: list[str] | None = None,
        scope: MemoryScope = MemoryScope.PROJECT,
        project: ProjectID | str = "default",
        owner: UserID | AgentID | str = "default",
        visibility: MemoryVisibility = MemoryVisibility.PRIVATE,
        importance: float = 0.5,
        confidence: float = 0.5,
        source: str = "manual",
        reason: str = "",
        created_by: AgentID | UserID | str = "system",
        parent: MemoryID | None = None,
    ) -> "MemoryEntry":
        """Convenience factory for creating a MemoryEntry in one call."""
        if isinstance(project, str):
            project = ProjectID(project)
        if isinstance(owner, str):
            owner = UserID(owner)
        if isinstance(created_by, str):
            created_by = AgentID(created_by)

        now = time.time()
        return cls(
            identity=MemoryIdentity(
                id=MemoryID(uuid.uuid4().hex),
                type=type,
                scope=scope,
                state=MemoryState.ACTIVE,
                created_by=created_by,
                created_at=now,
            ),
            content=MemoryContent(
                text=text,
                summary=summary,
                tags=tags or [],
                source=source,
                reason=reason,
            ),
            ownership=MemoryOwnership(
                project=project,
                owner=owner,
                visibility=visibility,
            ),
            score=MemoryScore(
                importance=importance,
                confidence=confidence,
                freshness=1.0,
                frequency=0,
                success_rate=0.5,
            ),
            relation=MemoryRelation(parent=parent),
            version=MemoryVersion(
                number=1,
                updated_by=created_by,
                updated_at=now,
                changelog=reason if reason else "Created",
            ),
        )
