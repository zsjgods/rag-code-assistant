"""Recovery — state persistence and restoration for the Context Engine.

RecoveryEngine is the SOLE entry point for saving and loading runtime state.
It depends on:
  - Store (for key-value persistence) — does NOT know about Store internals
  - Serializer (for data format) — uses serialize() / deserialize() dispatch

RecoveryEngine manages four namespaces:
  context.summary    → SummaryState (SummaryEntry entries + version)
  context.workspace  → WorkspaceState (cwd, git, files, task)
  context.session    → SessionState (timestamps, loop count, metadata)
  context.metadata   → Metadata (schema version, recovery count)

Architecture:
    RecoveryEngine
      ├── save_summary / load_summary
      ├── save_workspace / load_workspace
      ├── save_session / load_session
      └── save_metadata / load_metadata

Best-effort principle: each load is independent. If one namespace fails
(corrupt data, version mismatch), the others still recover.
"""

from src.context.recovery.recovery import (
    RecoveryEngine,
    SummaryState,
    WorkspaceState,
    SessionState,
)
from src.context.recovery.migration import (
    MigrationRegistry,
    MigrationError,
)

__all__ = [
    "RecoveryEngine",
    "SummaryState",
    "WorkspaceState",
    "SessionState",
    "MigrationRegistry",
    "MigrationError",
]
