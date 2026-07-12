"""RecoveryEngine — save/load runtime state for the Context Engine.

Single responsibility: serialize runtime state to Store, and restore it.

RecoveryEngine knows:
  - What keys to use in Store ("context.summary", "context.workspace", etc.)
  - What data shapes to save/load (SummaryState, WorkspaceState, SessionState)
  - What schema version each namespace uses

RecoveryEngine does NOT know:
  - How Store persists data (JSON, SQLite, Redis — irrelevant)
  - How Layers render context (that's Runtime's job)
  - What the current Objective or Persistent Facts are (those are live state)

Best-effort recovery: every load_*() call is independent.
If context.summary is corrupt, context.workspace can still be restored.
"""

import time as time_module
import logging
from dataclasses import dataclass, field
from typing import Any

from src.state.store import Store
from src.context.serialization import (
    serialize,
    deserialize,
    summary_entry_from_dict,
    summary_entry_to_dict,
)
from src.context.serialization.schema import KEY_SCHEMA, SCHEMA_VERSION
from src.context.layers.summary import SummaryEntry, SummaryLayer
from src.context.layers.workspace import WorkspaceLayer
from src.context.recovery.migration import MigrationRegistry


# ── Logging ────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


# ── Namespace keys ─────────────────────────────────────────────────────

NS_SUMMARY = "context.summary"
NS_WORKSPACE = "context.workspace"
NS_SESSION = "context.session"
NS_METADATA = "context.metadata"


# ── Serializable state containers ─────────────────────────────────────
# These are dicts with factory functions, not dataclasses.
# They serve as the interchange format between RecoveryEngine and Store.


def SummaryState(
    entries: list[SummaryEntry | dict] | None = None,
    version: int = 0,
) -> dict:
    """Create a SummaryState dict.

    Accepts both SummaryEntry objects and pre-serialized dicts.
    Dict entries are stored as-is; SummaryEntry objects are serialized.

    Returns:
        {"entries": [serialized SummaryEntry dicts], "version": int}
    """
    serialized: list[dict] = []
    for e in (entries or []):
        if isinstance(e, SummaryEntry):
            serialized.append(summary_entry_to_dict(e))
        else:
            serialized.append(dict(e))  # Already a dict
    return {
        "entries": serialized,
        "version": version,
        "_type": "SummaryState",
    }


def WorkspaceState(
    cwd: str = "",
    git_branch: str = "",
    dirty_files: list[str] | None = None,
    open_files: list[str] | None = None,
    recent_files: list[str] | None = None,
    current_task: str = "",
) -> dict:
    """Create a WorkspaceState dict."""
    return {
        "cwd": cwd,
        "git_branch": git_branch,
        "dirty_files": dirty_files or [],
        "open_files": open_files or [],
        "recent_files": recent_files or [],
        "current_task": current_task,
        "_type": "WorkspaceState",
    }


def SessionState(
    started_at: float = 0.0,
    last_active_at: float = 0.0,
    loop_count: int = 0,
    metadata: dict | None = None,
) -> dict:
    """Create a SessionState dict."""
    return {
        "started_at": started_at,
        "last_active_at": last_active_at,
        "loop_count": loop_count,
        "metadata": metadata or {},
        "_type": "SessionState",
    }


# ── RecoveryEngine ──────────────────────────────────────────────────────


class RecoveryEngine:
    """Save and load runtime state via Store.

    Usage:
        engine = RecoveryEngine(store)

        # Save on shutdown / checkpoint
        engine.save_summary(summary_layer)
        engine.save_workspace(workspace_layer)
        engine.save_session(session_data)

        # Load on startup
        summary_state = engine.load_summary()
        if summary_state:
            for entry_data in summary_state["entries"]:
                summary_layer.add_entry(entry_data)

    Best-effort: load_*() returns None on failure, never raises.
    """

    def __init__(
        self,
        store: Store,
        migration_registry: MigrationRegistry | None = None,
    ):
        """
        Args:
            store: The application's Store instance.
            migration_registry: Optional migration registry for schema upgrades.
                                If None, no migration is performed on load.
        """
        self._store = store
        self._migrations = migration_registry or MigrationRegistry()

    # ── Context key helpers ──────────────────────────────

    def _make_key(self, namespace: str, sub_key: str | None = None) -> str:
        """Build a Store key from a namespace and optional sub-key."""
        if sub_key:
            return f"{namespace}.{sub_key}"
        return namespace

    # ── Summary ──────────────────────────────────────────

    def save_summary(self, summary_layer: SummaryLayer) -> None:
        """Persist SummaryLayer state to Store.

        Args:
            summary_layer: The active SummaryLayer instance.
        """
        state = SummaryState(
            entries=summary_layer.entries,
            version=summary_layer._version,
        )
        self._store.set(NS_SUMMARY, state)
        self._update_metadata()
        log.debug(f"Saved summary state: {summary_layer.entry_count} entries, "
                   f"v{summary_layer._version}")

    def load_summary(self) -> dict | None:
        """Restore SummaryLayer state from Store.

        Returns:
            SummaryState dict with "entries" and "version" keys,
            or None if no saved state exists or recovery fails.
        """
        try:
            raw = self._store.get(NS_SUMMARY)
            if not raw:
                return None

            state = self._apply_migration(raw, NS_SUMMARY)

            # Validate structure
            if not isinstance(state, dict):
                log.warning(f"[recovery] {NS_SUMMARY}: expected dict, got {type(state).__name__}")
                return None

            entries_raw = state.get("entries", [])
            if not isinstance(entries_raw, list):
                log.warning(f"[recovery] {NS_SUMMARY}: 'entries' is not a list")
                entries_raw = []

            # Deserialize each entry (best-effort: skip corrupt entries)
            valid_entries: list[SummaryEntry] = []
            for i, entry_data in enumerate(entries_raw):
                try:
                    if isinstance(entry_data, dict):
                        valid_entries.append(summary_entry_from_dict(entry_data))
                    elif isinstance(entry_data, SummaryEntry):
                        valid_entries.append(entry_data)
                except Exception as e:
                    log.warning(f"[recovery] {NS_SUMMARY}: skipping corrupt entry {i}: {e}")

            result = {
                "entries": valid_entries,  # SummaryEntry objects
                "version": state.get("version", 0),
                "_type": "SummaryState",
            }
            log.debug(f"[recovery] Loaded summary: {len(valid_entries)} entries, "
                       f"v{result['version']}")
            return result

        except Exception as e:
            log.warning(f"[recovery] Failed to load {NS_SUMMARY}: {e}")
            return None

    # ── Workspace ────────────────────────────────────────

    def save_workspace(self, workspace_layer: WorkspaceLayer) -> None:
        """Persist WorkspaceLayer state to Store.

        Args:
            workspace_layer: The active WorkspaceLayer instance.
        """
        state = WorkspaceState(
            cwd=workspace_layer.cwd,
            git_branch=workspace_layer.git_branch,
            dirty_files=workspace_layer.dirty_files,
            open_files=workspace_layer.open_files,
            recent_files=workspace_layer.recent_files,
            current_task=workspace_layer.current_task,
        )
        self._store.set(NS_WORKSPACE, state)
        self._update_metadata()
        log.debug(f"Saved workspace state: cwd={state['cwd']}, "
                   f"branch={state['git_branch']}")

    def load_workspace(self) -> dict | None:
        """Restore WorkspaceLayer state from Store.

        Returns:
            WorkspaceState dict, or None if no saved state exists.
        """
        try:
            raw = self._store.get(NS_WORKSPACE)
            if not raw:
                return None

            state = self._apply_migration(raw, NS_WORKSPACE)
            if not isinstance(state, dict):
                log.warning(f"[recovery] {NS_WORKSPACE}: expected dict, got {type(state).__name__}")
                return None

            result = WorkspaceState(
                cwd=str(state.get("cwd", "")),
                git_branch=str(state.get("git_branch", "")),
                dirty_files=list(state.get("dirty_files", [])),
                open_files=list(state.get("open_files", [])),
                recent_files=list(state.get("recent_files", [])),
                current_task=str(state.get("current_task", "")),
            )
            log.debug(f"[recovery] Loaded workspace: cwd={result['cwd']}, "
                       f"branch={result['git_branch']}")
            return result

        except Exception as e:
            log.warning(f"[recovery] Failed to load {NS_WORKSPACE}: {e}")
            return None

    # ── Session ──────────────────────────────────────────

    def save_session(self, loop_count: int = 0, metadata: dict | None = None) -> None:
        """Persist session metadata to Store.

        Args:
            loop_count: Current agent loop iteration count.
            metadata: Additional session metadata dict.
        """
        now = time_module.time()
        existing = self.load_session()
        state = SessionState(
            started_at=existing.get("started_at", now) if existing else now,
            last_active_at=now,
            loop_count=loop_count,
            metadata={
                **(existing.get("metadata", {}) if existing else {}),
                **(metadata or {}),
            },
        )
        self._store.set(NS_SESSION, state)
        self._update_metadata()
        log.debug(f"Saved session: loop_count={loop_count}, "
                   f"started_at={state['started_at']:.0f}")

    def load_session(self) -> dict | None:
        """Restore session state from Store.

        Returns:
            SessionState dict, or None if no saved state exists.
        """
        try:
            raw = self._store.get(NS_SESSION)
            if not raw:
                return None

            state = self._apply_migration(raw, NS_SESSION)
            if not isinstance(state, dict):
                return None

            result = SessionState(
                started_at=float(state.get("started_at", 0.0)),
                last_active_at=float(state.get("last_active_at", 0.0)),
                loop_count=int(state.get("loop_count", 0)),
                metadata=dict(state.get("metadata", {})),
            )
            return result

        except Exception as e:
            log.warning(f"[recovery] Failed to load {NS_SESSION}: {e}")
            return None

    # ── Metadata ─────────────────────────────────────────

    def _update_metadata(self) -> None:
        """Update recovery metadata counters (internal, always succeeds)."""
        try:
            existing = self._load_metadata_raw()
            meta = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": time_module.time(),
                "created_at": existing.get("created_at", time_module.time()) if existing else time_module.time(),
                "recovery_count": existing.get("recovery_count", 0) if existing else 0,
            }
            self._store.set(NS_METADATA, meta)
        except Exception:
            pass  # Metadata is best-effort

    def _load_metadata_raw(self) -> dict | None:
        """Internal: load raw metadata dict without migration."""
        try:
            raw = self._store.get(NS_METADATA)
            return raw if isinstance(raw, dict) else None
        except Exception:
            return None

    def load_metadata(self) -> dict | None:
        """Load recovery metadata.

        Returns:
            Metadata dict with schema_version, created_at, updated_at,
            recovery_count, or None if never saved.
        """
        meta = self._load_metadata_raw()
        if meta:
            meta = self._apply_migration(meta, NS_METADATA)
        return meta

    # ── Generic save/load ────────────────────────────────

    def save(self, namespace: str, data: Any) -> None:
        """Generic save to a custom namespace.

        Args:
            namespace: Store key (e.g. "rag.index").
            data: Any serializable value.
        """
        self._store.set(namespace, data)

    def load(self, namespace: str) -> Any | None:
        """Generic load from a custom namespace.

        Args:
            namespace: Store key.

        Returns:
            The stored value, or None.
        """
        try:
            return self._store.get(namespace)
        except Exception as e:
            log.warning(f"[recovery] Failed to load {namespace}: {e}")
            return None

    # ── Clear ────────────────────────────────────────────

    def clear(self, namespace: str | None = None) -> None:
        """Clear saved state.

        Args:
            namespace: Specific namespace to clear, or None for all.
        """
        if namespace:
            self._store.set(namespace, None)
        else:
            for ns in (NS_SUMMARY, NS_WORKSPACE, NS_SESSION, NS_METADATA):
                self._store.set(ns, None)

    # ── Migration support ────────────────────────────────

    def _apply_migration(self, data: dict, namespace: str) -> dict:
        """Apply schema migration if needed.

        Checks the stored data's _schema version and migrates to the
        current SCHEMA_VERSION if a path exists.

        Args:
            data: Raw data dict from Store.
            namespace: Namespace key (for logging).

        Returns:
            Migrated data dict, or original if no migration needed.
        """
        if not isinstance(data, dict):
            return data

        stored_version = data.get(KEY_SCHEMA, "")
        if not stored_version or stored_version == SCHEMA_VERSION:
            return data

        if self._migrations.can_migrate(stored_version, SCHEMA_VERSION):
            log.info(
                f"[recovery] Migrating {namespace} from v{stored_version} "
                f"to v{SCHEMA_VERSION}"
            )
            return self._migrations.migrate(data, stored_version, SCHEMA_VERSION)

        log.warning(
            f"[recovery] {namespace}: stored schema v{stored_version} differs "
            f"from current v{SCHEMA_VERSION}, but no migration path found. "
            f"Attempting best-effort load."
        )
        return data
