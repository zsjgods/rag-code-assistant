"""Retrieval Query & Result data models — M7 Retrieval Engine.

Pure data — no dependencies on Store, VectorIndex, or Retriever.
"""

from dataclasses import dataclass, field

from src.memory.types import MemoryEntry


@dataclass
class RetrievalQuery:
    """Input to the retrieval pipeline.

    All fields except `text` are optional filters.
    """

    text: str = ""  # Query text (required for keyword + vector search)

    # Filters
    type_filter: list[str] | None = None  # MemoryType values
    tag_filter: list[str] | None = None
    project_filter: str | None = None
    scope_filter: list[str] | None = None  # MemoryScope values
    min_importance: float = 0.0
    max_results: int = 10

    # Channel weights override (optional — falls back to config)
    channel_weights: dict[str, float] | None = None

    def clone(self, **overrides) -> "RetrievalQuery":
        """Create a copy with field overrides."""
        d = {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
        d.update(overrides)
        return RetrievalQuery(**d)


@dataclass
class RetrievalResult:
    """Output of a single retriever channel (pre-fusion)."""

    id: str  # MemoryID.value
    score: float  # Channel-specific score (cosine similarity / keyword relevance / recency)
    source: str  # "keyword" | "vector" | "recent"

    # Post-rerank
    final_score: float = 0.0

    # Lazy-resolved entry (populated by Reranker or FormatStage)
    entry: MemoryEntry | None = field(default=None, compare=False)

    @property
    def id_str(self) -> str:
        return self.id
