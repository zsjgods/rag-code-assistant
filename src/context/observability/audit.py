"""AuditLog — records every pipeline build as a complete audit entry.

Each audit entry contains:
  - The full SelectionResult (with PromptPackage, Candidates, Stats)
  - A DashboardSnapshot (pre-computed metrics)
  - Timestamp and metadata

AuditLog supports:
  - In-memory ring buffer (default, max_entries configurable)
  - Optional Store persistence (for crash recovery audit trail)
  - Query by count and time range

Usage:
    audit = AuditLog()

    # Record after every pipeline run
    audit.record(selection_result=result, metadata={"round": 5})

    # View recent entries
    for entry in audit.recent(5):
        print(entry["dashboard"].summary_line())

    # Persist to Store (optional)
    audit = AuditLog(store=store)
"""

import time as time_module
from typing import Any

from src.context.selection.packer import SelectionResult
from src.context.observability.dashboard import DashboardBuilder
from src.context.observability.snapshot import DashboardSnapshot
from src.context.serialization import serialize


class AuditLog:
    """Ring-buffer audit log for Context Engine pipeline runs.

    Each call to record() appends an entry with:
      - timestamp: When this build happened
      - selection_result: Full serialized SelectionResult
      - dashboard: Pre-computed DashboardSnapshot
      - metadata: User-provided metadata

    The ring buffer holds up to max_entries (default 1000).
    Oldest entries are dropped when the buffer is full.
    """

    def __init__(
        self,
        store: Any | None = None,
        max_entries: int = 1000,
        namespace: str = "audit.log",
    ):
        """
        Args:
            store: Optional Store for persistence.
            max_entries: Maximum in-memory entries (ring buffer).
            namespace: Store key for persisted audit log.
        """
        self._store = store
        self._max = max_entries
        self._namespace = namespace
        self._entries: list[dict] = []
        self._counter: int = 0

    # ── Recording ────────────────────────────────────────

    def record(
        self,
        selection_result: SelectionResult | None = None,
        dashboard: DashboardSnapshot | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Record an audit entry.

        Args:
            selection_result: The full SelectionResult from the pipeline run.
            dashboard: Optional pre-computed DashboardSnapshot.
                       If not provided, computed from selection_result.
            metadata: Additional metadata (round number, trigger, etc.).

        Returns:
            The entry ID (monotonic counter).
        """
        self._counter += 1
        now = time_module.time()

        # Build dashboard if not provided
        if dashboard is None and selection_result is not None:
            dashboard = DashboardBuilder.quick(
                selection_result=selection_result,
                metadata=metadata,
            )
        elif dashboard is None:
            dashboard = DashboardBuilder.build(metadata=metadata)

        entry: dict = {
            "id": self._counter,
            "timestamp": now,
            "dashboard": dashboard.to_dict() if dashboard else {},
            "metadata": dict(metadata or {}),
        }

        # Serialize SelectionResult (full data) — lazy: only when requested
        if selection_result is not None:
            entry["selection_result_raw"] = serialize(selection_result)

        # Ring buffer
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries.pop(0)

        # Optional Store persistence
        if self._store is not None:
            try:
                self._store.set(self._namespace, self._entries[-100:])  # Keep last 100
            except Exception:
                pass  # Persistence is best-effort

        return self._counter

    # ── Query ─────────────────────────────────────────────

    def recent(self, n: int = 10) -> list[dict]:
        """Return the N most recent entries.

        Args:
            n: Maximum number of entries to return.

        Returns:
            List of audit entry dicts (newest first).
        """
        return list(reversed(self._entries[-n:]))

    def by_id(self, entry_id: int) -> dict | None:
        """Find an entry by its ID.

        Args:
            entry_id: The entry ID (from record() return value).

        Returns:
            The audit entry dict, or None.
        """
        for entry in reversed(self._entries):
            if entry["id"] == entry_id:
                return entry
        return None

    def since(self, timestamp: float) -> list[dict]:
        """Return all entries since a given timestamp.

        Args:
            timestamp: Unix timestamp.

        Returns:
            List of audit entry dicts (newest first).
        """
        return [
            e for e in reversed(self._entries)
            if e["timestamp"] >= timestamp
        ]

    # ── Stats ─────────────────────────────────────────────

    @property
    def total_entries(self) -> int:
        """Total entries recorded since creation."""
        return self._counter

    @property
    def buffered_entries(self) -> int:
        """Number of entries currently in the ring buffer."""
        return len(self._entries)

    @property
    def max_entries(self) -> int:
        """Maximum ring buffer size."""
        return self._max

    # ── Control ───────────────────────────────────────────

    def clear(self) -> None:
        """Clear all buffered entries. Counter is preserved."""
        self._entries.clear()

    def reset(self) -> None:
        """Clear all entries AND reset the counter."""
        self._entries.clear()
        self._counter = 0
