"""Retrievers — Keyword, Vector, and Recent memory retrieval channels.

Each Retriever implements the same abstract interface.
HybridRetriever combines all three in hybrid.py.
"""

from abc import ABC, abstractmethod

from src.memory.identity import MemoryID
from src.memory.retrieval.query import RetrievalQuery, RetrievalResult
from src.memory.types import MemoryEntry


class Retriever(ABC):
    """Abstract retriever — one channel of memory retrieval."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique channel name: 'keyword', 'vector', 'recent'."""
        ...

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        """Search memories and return scored results.

        Args:
            query: Retrieval query with text + filters.

        Returns:
            List of RetrievalResult sorted by score descending.
        """
        ...


# ═══════════════════════════════════════════════════════════════════
# KeywordRetriever
# ═══════════════════════════════════════════════════════════════════

class KeywordRetriever(Retriever):
    """TF-IDF weighted keyword search over memory content, summary, and tags.

    Scoring: content (1x) + summary (3x) + tag (5x), normalized by text length.
    """

    name = "keyword"

    def __init__(self, store):
        self._store = store

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        keywords = query.text.lower().split()
        if not keywords:
            return []

        results: list[RetrievalResult] = []

        for entry in self._store.get_active().values():
            # Apply filters
            if query.type_filter and entry.type.value not in query.type_filter:
                continue
            if query.tag_filter:
                entry_tags = {t.lower() for t in entry.content.tags}
                if not entry_tags.intersection(t.lower() for t in query.tag_filter):
                    continue
            if query.project_filter and entry.project.value != query.project_filter:
                continue
            if entry.importance < query.min_importance:
                continue

            content_lower = entry.content.text.lower()
            summary_lower = entry.content.summary.lower()
            tags_lower = [t.lower() for t in entry.content.tags]

            score = 0.0
            for kw in keywords:
                # Content matches (1x)
                score += content_lower.count(kw) * 1.0
                # Summary matches (3x — more signal)
                score += summary_lower.count(kw) * 3.0
                # Tag matches (5x — highest signal)
                if any(kw in t for t in tags_lower):
                    score += 5.0

            # Normalize by content length (avoid long entries dominating)
            text_len = max(1, len(content_lower))
            score = score / (text_len ** 0.3)  # Sub-linear normalization

            if score > 0:
                results.append(RetrievalResult(
                    id=entry.id_str,
                    score=score,
                    source="keyword",
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:query.max_results * 3]  # Return more than needed for fusion


# ═══════════════════════════════════════════════════════════════════
# VectorRetriever
# ═══════════════════════════════════════════════════════════════════

class VectorRetriever(Retriever):
    """Semantic vector search using BaseVectorIndex.

    Depends on BaseVectorIndex (interface), NOT NumPyVectorIndex (concrete).
    Future FAISS/Milvus implementations work without changing this code.
    """

    name = "vector"

    def __init__(self, vector_index, embedder, store):
        self._vector_index = vector_index  # BaseVectorIndex
        self._embedder = embedder  # DenseEmbedder-compatible
        self._store = store

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        if not query.text.strip():
            return []

        # Embed query
        query_vec = self._embedder.embed_query(query.text)  # → (dim,) float32

        # Search vector index
        raw_results = self._vector_index.search(
            query_vec, top_k=query.max_results * 3
        )

        # Resolve IDs to entries for filtering
        results: list[RetrievalResult] = []
        for id_str, score in raw_results:
            entry = self._store.read(MemoryID(id_str))
            if entry is None:
                continue

            # Apply filters
            if query.type_filter and entry.type.value not in query.type_filter:
                continue
            if query.tag_filter:
                entry_tags = {t.lower() for t in entry.content.tags}
                if not entry_tags.intersection(t.lower() for t in query.tag_filter):
                    continue
            if query.project_filter and entry.project.value != query.project_filter:
                continue
            if entry.importance < query.min_importance:
                continue

            results.append(RetrievalResult(
                id=id_str,
                score=score,
                source="vector",
            ))

        return results[:query.max_results * 3]


# ═══════════════════════════════════════════════════════════════════
# RecentRetriever
# ═══════════════════════════════════════════════════════════════════

class RecentRetriever(Retriever):
    """Recent-memory-first retrieval channel.

    Returns the most recently created active memories. This ensures that
    recent context is never lost, even when it doesn't match keywords
    or semantic queries.
    """

    name = "recent"

    def __init__(self, store):
        self._store = store

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        active = list(self._store.get_active().values())

        # Apply filters
        filtered = []
        for entry in active:
            if query.type_filter and entry.type.value not in query.type_filter:
                continue
            if query.tag_filter:
                entry_tags = {t.lower() for t in entry.content.tags}
                if not entry_tags.intersection(t.lower() for t in query.tag_filter):
                    continue
            if query.project_filter and entry.project.value != query.project_filter:
                continue
            if entry.importance < query.min_importance:
                continue
            filtered.append(entry)

        # Sort by created_at descending (most recent first)
        filtered.sort(key=lambda e: e.identity.created_at, reverse=True)

        # Score: 1.0 for most recent, linear decay to 0.0 for oldest
        results = []
        n = max(1, len(filtered))
        for i, entry in enumerate(filtered[:query.max_results * 3]):
            recency_score = 1.0 - (i / n)
            results.append(RetrievalResult(
                id=entry.id_str,
                score=recency_score,
                source="recent",
            ))

        return results
