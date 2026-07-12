"""Hybrid Fusion — combine keyword, vector, and recent retrieval results.

Two fusion strategies:
  - WeightedSumFusion: normalize scores, weighted sum, merge duplicates
  - ReciprocalRankFusion (RRF): 1/(k + rank), more robust across channels
"""

from abc import ABC, abstractmethod

from src.memory.retrieval.config import RetrievalConfig
from src.memory.retrieval.query import RetrievalQuery, RetrievalResult
from src.memory.retrieval.retriever import Retriever


class HybridFusion(ABC):
    """Abstract fusion strategy."""

    @abstractmethod
    def fuse(
        self,
        channel_results: dict[str, list[RetrievalResult]],
    ) -> list[RetrievalResult]:
        """Combine results from multiple channels into a single ranked list."""
        ...


# ═══════════════════════════════════════════════════════════════════
# WeightedSumFusion
# ═══════════════════════════════════════════════════════════════════

class WeightedSumFusion(HybridFusion):
    """Normalize per-channel scores, apply weights, merge duplicates."""

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or {"keyword": 0.3, "vector": 0.5, "recent": 0.2}

    def fuse(
        self,
        channel_results: dict[str, list[RetrievalResult]],
    ) -> list[RetrievalResult]:
        # Normalize each channel's scores to [0, 1]
        normalized: dict[str, list[RetrievalResult]] = {}
        for channel, results in channel_results.items():
            if not results:
                normalized[channel] = []
                continue
            max_score = max(r.score for r in results)
            min_score = min(r.score for r in results)
            score_range = max_score - min_score or 1.0
            for r in results:
                r.score = (r.score - min_score) / score_range
            normalized[channel] = results

        # Merge: id → max weighted score
        merged: dict[str, RetrievalResult] = {}
        for channel, results in normalized.items():
            weight = self._weights.get(channel, 0.0)
            if weight == 0.0:
                continue
            for r in results:
                weighted = r.score * weight
                if r.id not in merged or weighted > merged[r.id].score:
                    r.score = weighted
                    merged[r.id] = r

        # Sort by score descending
        return sorted(merged.values(), key=lambda r: r.score, reverse=True)


# ═══════════════════════════════════════════════════════════════════
# ReciprocalRankFusion (RRF)
# ═══════════════════════════════════════════════════════════════════

class ReciprocalRankFusion(HybridFusion):
    """RRF: score = 1 / (k + rank). No score normalization needed.

    More robust when channel score distributions differ significantly.
    """

    def __init__(self, k: int = 60):
        self._k = k

    def fuse(
        self,
        channel_results: dict[str, list[RetrievalResult]],
    ) -> list[RetrievalResult]:
        merged: dict[str, float] = {}  # id → accumulated RRF score

        for channel, results in channel_results.items():
            for rank, r in enumerate(results):
                rrf_score = 1.0 / (self._k + rank + 1)
                merged[r.id] = merged.get(r.id, 0.0) + rrf_score
                r.score = rrf_score  # Store channel-level RRF score

        # Build results
        output = []
        for id_str, score in merged.items():
            # Find the original result to preserve source info
            source = "hybrid"
            for results in channel_results.values():
                for r in results:
                    if r.id == id_str and r.source:
                        source = r.source
                        break
            output.append(RetrievalResult(id=id_str, score=score, source=source))

        return sorted(output, key=lambda r: r.score, reverse=True)


# ═══════════════════════════════════════════════════════════════════
# HybridRetriever
# ═══════════════════════════════════════════════════════════════════

class HybridRetriever:
    """Three-channel hybrid retrieval: keyword + vector + recent.

    Usage:
        hr = HybridRetriever(
            retrievers=[KeywordRetriever(store), VectorRetriever(idx, emb, store), RecentRetriever(store)],
            fusion=WeightedSumFusion(weights={"keyword": 0.3, "vector": 0.5, "recent": 0.2}),
        )
        results = hr.retrieve(RetrievalQuery(text="testing tools"))
    """

    def __init__(
        self,
        retrievers: list[Retriever],
        fusion: HybridFusion | None = None,
        config: RetrievalConfig | None = None,
    ):
        self._retrievers: dict[str, Retriever] = {r.name: r for r in retrievers}
        self._config = config or RetrievalConfig()

        if fusion:
            self._fusion = fusion
        elif self._config.fusion_strategy == "rrf":
            self._fusion = ReciprocalRankFusion(k=self._config.rrf_k)
        else:
            self._fusion = WeightedSumFusion(weights=self._config.channel_weights)

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        # Collect results from each channel
        channel_results: dict[str, list[RetrievalResult]] = {}
        for name, retriever in self._retrievers.items():
            channel_results[name] = retriever.retrieve(query)

        # Fusion
        fused = self._fusion.fuse(channel_results)
        return fused[:query.max_results * 2]  # Return more for Reranker
