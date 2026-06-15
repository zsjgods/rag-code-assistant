"""Embedding wrapper — TF-IDF for coarse ranking + dense for fine ranking.

Uses sklearn TfidfVectorizer as the default dense-free embedding.
When Anthropic API is available, can optionally use it for dense embeddings.
"""

import pickle
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class Embedder:
    """TF-IDF based embedder for code chunks.

    Treats each chunk's code + signature as a document.
    Supports save/load for persistence.
    """

    def __init__(self, max_features: int = 5000, ngram_range: tuple = (1, 2)):
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=ngram_range,
            stop_words=None,         # code has no natural stop words
            sublinear_tf=True,       # 1 + log(tf) — dampens repeated terms
        )
        self.fitted = False
        self._chunk_vectors: np.ndarray = None

    # ── build ────────────────────────────────────────────────

    def fit(self, documents: list[str]) -> np.ndarray:
        """Fit the vectorizer and return document matrix.

        Args:
            documents: list of chunk texts (code + signature)

        Returns:
            (n_docs, n_features) sparse? → dense float32 matrix
        """
        self._chunk_vectors = self.vectorizer.fit_transform(documents).toarray().astype(np.float32)
        self.fitted = True
        return self._chunk_vectors

    # ── query ────────────────────────────────────────────────

    def embed_query(self, query: str) -> np.ndarray:
        """Convert a search query into the same vector space.

        Returns:
            (1, n_features) float32 array
        """
        if not self.fitted:
            raise RuntimeError("Embedder not fitted — call fit() first")
        return self.vectorizer.transform([query]).toarray().astype(np.float32)

    def embed_chunks(self, documents: list[str]) -> np.ndarray:
        """Transform documents using the already-fitted vectorizer."""
        if not self.fitted:
            raise RuntimeError("Embedder not fitted — call fit() first")
        return self.vectorizer.transform(documents).toarray().astype(np.float32)

    # ── similarity ───────────────────────────────────────────

    def similarity(self, query_vec: np.ndarray, chunk_vecs: np.ndarray = None) -> np.ndarray:
        """Cosine similarity between query and all chunks.

        Returns:
            1-D array of scores, shape (n_chunks,)
        """
        if chunk_vecs is None:
            chunk_vecs = self._chunk_vectors
        sim = cosine_similarity(query_vec.reshape(1, -1), chunk_vecs)
        return sim.flatten()

    # ── persistence ──────────────────────────────────────────

    def save(self, path: str | Path):
        """Pickle the fitted vectorizer and chunk vectors."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vectorizer": self.vectorizer,
            "chunk_vectors": self._chunk_vectors,
            "fitted": self.fitted,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str | Path):
        """Load a pickled embedder."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Embedder file not found: {path}")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.vectorizer = data["vectorizer"]
        self._chunk_vectors = data["chunk_vectors"]
        self.fitted = data["fitted"]
