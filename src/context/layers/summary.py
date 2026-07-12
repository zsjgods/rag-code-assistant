"""SummaryLayer — pure storage for compressed conversation history.

Stores SummaryEntry objects. M3 keeps a single rolling summary entry.
The layer is passive — it never initiates compression, never calculates
budgets, never decides what to keep. It only stores and retrieves.

CompressionPipeline writes to it (layer.update() or layer.add_entry()).
PromptBuilder reads from it (layer.render()).
"""

import time as time_module
from dataclasses import dataclass, field
from typing import Any

from src.context.layers.base import BaseLayer


# ── SummaryEntry ────────────────────────────────────────────────────────


@dataclass
class SummaryEntry:
    """A single compression artifact.

    M3 maintains one rolling entry (latest summary).
    M4 may keep multiple entries for retrieval.

    Lifecycle fields (for M4+ compression/eviction decisions):
      importance:   0.0–1.0 (higher = more likely to survive secondary compression)
      last_used_at: Timestamp of last render (used for LRU eviction)
      access_count: How many times render() included this entry
    """

    content: str
    token_count: int
    version: int = 0
    created_at: float = 0.0
    last_used_at: float = 0.0
    importance: float = 1.0
    access_count: int = 0
    source: str = ""  # "tier3" | "manual" | "recovery"
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last_used_at and access_count on render."""
        self.last_used_at = time_module.time()
        self.access_count += 1


# ── SummaryLayer ────────────────────────────────────────────────────────


class SummaryLayer(BaseLayer):
    """Stores and renders compressed conversation history.

    Responsibilities:
      - Store SummaryEntry objects
      - Render the latest entry as a messages[] block
      - Track last_used_at per entry for future eviction decisions
      - Provide token_count() for BudgetManager

    Non-responsibilities:
      - Initiating compression (→ CompressionPolicy)
      - Performing compression (→ CompressionPipeline)
      - Budget calculation (→ BudgetManager)
    """

    is_immutable = False

    def __init__(self):
        self._entries: list[SummaryEntry] = []
        self._version: int = 0

    @property
    def name(self) -> str:
        return "summary"

    # ── Storage ─────────────────────────────────────────

    def update(self, content: str, source: str = "tier3", importance: float = 1.0) -> SummaryEntry:
        """Create and store a new summary entry (rolling mode).

        M3 keeps only the latest entry — previous entries are replaced.
        M4 may change this behavior to retain multiple entries.

        Args:
            content: Summary text.
            source: Origin identifier ("tier3", "manual", "recovery").
            importance: 0.0–1.0, for future compression/eviction decisions.

        Returns:
            The newly created SummaryEntry.
        """
        self._version += 1
        now = time_module.time()
        entry = SummaryEntry(
            content=content,
            token_count=len(content) // 4,
            version=self._version,
            created_at=now,
            last_used_at=now,
            importance=importance,
            access_count=0,
            source=source,
        )
        # M3: rolling mode — replace any existing entry
        self._entries = [entry]
        return entry

    def add_entry(self, entry: SummaryEntry) -> None:
        """Append an externally-created entry.

        Used by M4+ when multiple summaries are retained,
        or by RecoveryEngine to restore from persistence.
        """
        self._version = max(self._version, entry.version)
        self._entries.append(entry)

    # ── Render ──────────────────────────────────────────

    def render(self) -> list[dict]:
        """Render stored entries as messages[] blocks.

        Returns:
            A list with one message per entry, wrapped in <summary> tags.
            Empty list if no entries.
        """
        if not self._entries:
            return []

        blocks: list[dict] = []
        for entry in self._entries:
            entry.touch()
            content = f"<summary>\n{entry.content}\n</summary>"
            blocks.append({"role": "user", "content": content})

        return blocks

    # ── Accessors ───────────────────────────────────────

    def get_latest(self) -> SummaryEntry | None:
        """Return the most recent entry, or None if empty."""
        return self._entries[-1] if self._entries else None

    @property
    def entries(self) -> list[SummaryEntry]:
        """All stored entries (read-only view)."""
        return list(self._entries)

    @property
    def entry_count(self) -> int:
        """Number of stored entries."""
        return len(self._entries)

    # ── Token count ─────────────────────────────────────

    def token_count(self) -> int:
        """Sum of all stored entries' token counts."""
        return sum(e.token_count for e in self._entries)

    # ── BaseLayer interface ─────────────────────────────

    def clear(self) -> None:
        """Remove all entries and reset version counter."""
        self._entries.clear()
        self._version = 0
