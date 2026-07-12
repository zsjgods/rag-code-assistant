"""Memory Identity — unified ID types for multi-Agent, multi-Workspace collaboration.

All ID types are frozen (immutable) and hashable — safe as dict keys and set members.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryID:
    """Unique identifier for a single memory entry."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserID:
    """Identifies a human user."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ProjectID:
    """Identifies a project (codebase / repository / team initiative)."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class WorkspaceID:
    """Identifies a workspace (a user's working copy of a project)."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SessionID:
    """Identifies a single agent session / conversation."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AgentID:
    """Identifies an agent instance."""
    value: str

    def __str__(self) -> str:
        return self.value
