"""Reranker — second-pass ranking after hybrid retrieval.

Multi-dimensional scoring:
  final = relevance^α × importance^β × freshness^γ × frequency^δ

The Reranker reads MemoryEntry from Store to access score fields.
"""

from src.memory.identity import MemoryID
from src.memory.retrieval.config import RerankWeights
from src.memory.retrieval.query import RetrievalResult


class Reranker:
    """Post-retrieval reranking using MemoryScore dimensions.

    After HybridRetriever returns candidates, Reranker applies:
      - importance (MemoryScore.importance)
      - freshness  (MemoryScore.freshness — decays over time)
      - frequency  (MemoryScore.frequency — access count)

    Usage:
        reranker = Reranker(weights=RerankWeights(relevance=1.0, importance=0.5))
        final = reranker.rerank(candidates, store)
    """

    def __init__(self, weights: RerankWeights | None = None):
        self._weights = weights or RerankWeights()

    def rerank(
        self,
        candidates: list[RetrievalResult],
        store,
    ) -> list[RetrievalResult]:
        """Apply multi-dimensional scoring to candidates.

        Args:
            candidates: Results from HybridRetriever.
            store: MemoryStore (for reading entry scores).

        Returns:
            Same list with final_score populated, sorted by final_score descending.
        """
        for c in candidates:
            entry = store.read(MemoryID(c.id))
            if entry is None:
                c.final_score = 0.0
                continue

            c.entry = entry  # Lazy-resolve for downstream stages

            # Multiplicative scoring:
            # final = relevance^α × importance^β × freshness^γ × frequency^δ
            rel = max(c.score, 1e-6) ** self._weights.relevance

            imp = max(entry.importance, 1e-6) ** self._weights.importance

            fresh = max(entry.freshness, 1e-6) ** self._weights.freshness

            # frequency: use log to dampen (avoid high-frequency dominating)
            freq_log = max(1.0, float(entry.frequency))
            freq = freq_log ** self._weights.frequency

            c.final_score = rel * imp * fresh * freq

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates
