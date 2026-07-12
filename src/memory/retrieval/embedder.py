"""Semantic embedder — multilingual sentence embeddings for memory retrieval.

Uses sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2).
Produces 384-dim dense vectors for semantic search over memory entries.
Supports Chinese + English + code queries.

Moved from src/rag/embedder_dense.py — now lives alongside the retrieval engine.
"""

import pickle
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class DenseEmbedder:
    """Semantic embedder using sentence-transformers.

    Produces 384-dim dense vectors. Unlike TF-IDF (lexical match),
    this captures semantic meaning — "删除" will match "remove/delete".
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.fitted = False
        self._chunk_vectors: np.ndarray = None

    # ── build ────────────────────────────────────────────────

    def fit(self, documents: list[str]) -> np.ndarray:
        """Encode all documents into dense vectors.

        Returns:
            (n_docs, 384) float32 array
        """
        self._chunk_vectors = self.model.encode(
            documents,
            normalize_embeddings=True,    # cos_sim = dot product after norm
            show_progress_bar=True,
        ).astype(np.float32)
        self.fitted = True
        return self._chunk_vectors

    # ── query ────────────────────────────────────────────────

    def embed_query(self, query: str) -> np.ndarray:
        """Encode a query into the same vector space.

        Returns:
            (1, 384) float32 array
        """
        if not self.fitted:
            raise RuntimeError("DenseEmbedder not fitted — call fit() first")
        return self.model.encode(
            [query],
            normalize_embeddings=True,
        ).astype(np.float32)

    def embed_chunks(self, documents: list[str]) -> np.ndarray:
        """Encode new documents using the same model."""
        return self.model.encode(
            documents,
            normalize_embeddings=True,
        ).astype(np.float32)

    # ── similarity ───────────────────────────────────────────

    def similarity(self, query_vec: np.ndarray, chunk_vecs: np.ndarray = None) -> np.ndarray:
        """Cosine similarity.

        Returns:
            1-D array of scores, shape (n_chunks,)
        """
        if chunk_vecs is None:
            chunk_vecs = self._chunk_vectors
        sim = cosine_similarity(query_vec.reshape(1, -1), chunk_vecs)
        return sim.flatten()

    # ── persistence ──────────────────────────────────────────

    def save(self, path: str | Path):
        """Save chunk vectors + model name. Model itself is reloaded from HF."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model_name": self.model_name,
            "chunk_vectors": self._chunk_vectors,
            "fitted": self.fitted,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str | Path):
        """Load pickled vectors. Model is re-downloaded from HF if needed."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Dense embedder file not found: {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model_name = data["model_name"]
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(self.model_name)
        self._chunk_vectors = data["chunk_vectors"]
        self.fitted = data["fitted"]
