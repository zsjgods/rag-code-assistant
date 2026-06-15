"""Two-stage retrieval: coarse (TF-IDF) → fine (cosine similarity)."""

import numpy as np

from .chunker import CodeChunk
from .embedder import Embedder


class Retriever:
    """Two-stage code search.

    Stage 1 (coarse): TF-IDF keyword match → top-K1
    Stage 2 (fine):   cosine similarity on dense vectors → top-K2
    """

    def __init__(self, embedder: Embedder, chunks: list[CodeChunk],
                 coarse_k: int = 50, fine_k: int = 10):
        """
        Args:
            embedder: fitted Embedder instance
            chunks:   all indexed CodeChunks
            coarse_k: candidates from stage 1
            fine_k:   final results from stage 2
        """
        self.embedder = embedder
        self.chunks = chunks
        self.coarse_k = coarse_k
        self.fine_k = fine_k
        self._chunk_vectors = embedder._chunk_vectors  # (n_chunks, n_features)

    def search(self, query: str, top_k: int = None) -> list[dict]:
        """Search for code chunks matching the query.

        Args:
            query: natural language or code query
            top_k: number of results (default: self.fine_k)

        Returns:
            list of dicts with keys:
              file, symbol, type, lines, code (truncated), score, rank
        """
        top_k = top_k or self.fine_k
        if not self.chunks:
            return []

        # ── Stage 1: coarse TF-IDF ────────────────────────────
        q_vec = self.embedder.embed_query(query)
        scores = self.embedder.similarity(q_vec, self._chunk_vectors)

        # Top-K1 candidates
        coarse_n = min(self.coarse_k, len(scores))
        if coarse_n == 0:
            return []

        coarse_idx = np.argpartition(scores, -coarse_n)[-coarse_n:]
        coarse_idx = coarse_idx[np.argsort(scores[coarse_idx])[::-1]]

        # ── Stage 2: fine re-rank ─────────────────────────────
        # In this version, stage 2 re-ranks via the same cosine scores.
        # When dense embeddings (e.g. from Anthropic API) are added,
        # they replace the fine-stage vectors while TF-IDF remains coarse.
        fine_n = min(top_k, len(coarse_idx))
        top_indices = coarse_idx[:fine_n]
        top_scores = scores[top_indices]

        results = []
        for rank, (idx, score) in enumerate(zip(top_indices, top_scores), 1):
            c = self.chunks[idx]
            code_preview = c.code[:600] + ("..." if len(c.code) > 600 else "")
            results.append({
                "file": c.file_path,
                "symbol": c.symbol_name,
                "type": c.symbol_type,
                "lines": f"{c.start_line}-{c.end_line}",
                "code": code_preview,
                "score": round(float(score), 4),
                "rank": rank,
            })

        return results

    def search_raw(self, query: str, top_k: int = None) -> list[CodeChunk]:
        """Search and return full CodeChunk objects (for tool use)."""
        top_k = top_k or self.fine_k
        results = self.search(query, top_k)
        out = []
        for r in results:
            for c in self.chunks:
                if c.file_path == r["file"] and c.symbol_name == r["symbol"]:
                    out.append(c)
                    break
        return out
