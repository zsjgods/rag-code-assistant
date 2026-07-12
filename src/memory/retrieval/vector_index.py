"""BaseVectorIndex — abstract vector index interface.

M7 provides NumPyVectorIndex (brute-force cosine). Future implementations
(FAISS, HNSW, Milvus, Qdrant) implement the same interface — zero changes
to Retriever or any other M7 module.
"""

import pickle
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np


class BaseVectorIndex(ABC):
    """Abstract vector index for semantic memory retrieval.

    All Retriever code depends on this interface — never on NumPyVectorIndex directly.
    """

    @abstractmethod
    def initialize(self, dim: int) -> None:
        """Initialize the index structure (allocate memory, create ANN graph, etc.).

        Must be called before add() or search().
        """
        ...

    @abstractmethod
    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        """Add vectors to the index.

        Args:
            ids: MemoryID.value strings, ids[i] corresponds to vectors[i].
            vectors: (n, dim) float32 numpy array.
        """
        ...

    @abstractmethod
    def update(self, id: str, vector: np.ndarray) -> None:
        """Update a single vector. Adds it if not present.

        Args:
            id: MemoryID.value.
            vector: (dim,) float32 numpy array.
        """
        ...

    @abstractmethod
    def remove(self, ids: list[str]) -> None:
        """Remove vectors from the index. Silently ignores IDs not present."""
        ...

    @abstractmethod
    def search(
        self, query: np.ndarray, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Search for nearest neighbors.

        Args:
            query: (dim,) float32 query vector.
            top_k: Number of results to return.

        Returns:
            [(id: str, score: float), ...] sorted by score descending.
            Score is cosine similarity (0.0–1.0, higher = more similar).
        """
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist the index to disk."""
        ...

    @abstractmethod
    def load(self, path: Path) -> None:
        """Restore the index from disk."""
        ...

    @abstractmethod
    def rebuild(self) -> None:
        """Full rebuild from source data (e.g. MetadataStore).
        Used for disaster recovery or index corruption.
        """
        ...

    @abstractmethod
    def stats(self) -> dict:
        """Return index statistics: {dim, count, memory_bytes, ...}."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all vectors and reset the index."""
        ...

    def __len__(self) -> int:
        """Number of vectors in the index."""
        return self.stats().get("count", 0)


# ═══════════════════════════════════════════════════════════════════
# NumPyVectorIndex — brute-force cosine similarity
# ═══════════════════════════════════════════════════════════════════

class NumPyVectorIndex(BaseVectorIndex):
    """In-memory brute-force cosine similarity using numpy.

    Suitable for up to ~50K vectors at 384-dim (≈76 MB).
    Beyond that, replace with FAISSVectorIndex implementing the same interface.

    Internal structure:
      _ids: list[str]           — ordered ID list
      _vectors: np.ndarray       — (n, dim) float32, L2-normalized
      _id_to_idx: dict[str, int] — id → index in _ids/_vectors

    Search:
      scores = query_vec @ _vectors.T  (cosine, since vectors are normalized)
      top_k = np.argpartition(-scores, top_k)[:top_k]
    """

    def __init__(self):
        self._dim: int | None = None
        self._ids: list[str] = []
        self._vectors: np.ndarray | None = None  # (n, dim) float32
        self._id_to_idx: dict[str, int] = {}

    # ── BaseVectorIndex implementation ────────────────────────

    def initialize(self, dim: int) -> None:
        self._dim = dim
        self._ids = []
        self._vectors = np.empty((0, dim), dtype=np.float32)
        self._id_to_idx = {}

    def add(self, ids: list[str], vectors: np.ndarray) -> None:
        if self._dim is None:
            self.initialize(vectors.shape[1])

        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        # Normalize
        vectors = self._normalize(vectors)

        for i, id_str in enumerate(ids):
            if id_str in self._id_to_idx:
                # Update existing
                idx = self._id_to_idx[id_str]
                self._vectors[idx] = vectors[i]
            else:
                # Append
                self._id_to_idx[id_str] = len(self._ids)
                self._ids.append(id_str)

        # Rebuild array (batch append)
        if self._vectors is not None and self._vectors.shape[0] == len(self._ids) - len(ids):
            self._vectors = np.vstack([self._vectors, vectors])
        elif self._vectors is not None:
            # Some were updates — rebuild from scratch
            new_vecs = np.zeros((len(self._ids), self._dim), dtype=np.float32)
            for idx, id_str in enumerate(self._ids):
                new_vecs[idx] = self._vectors[self._id_to_idx.get(id_str, idx)]
            self._vectors = new_vecs

    def update(self, id: str, vector: np.ndarray) -> None:
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        vector = self._normalize(vector)

        if id in self._id_to_idx:
            idx = self._id_to_idx[id]
            self._vectors[idx] = vector[0]
        else:
            self._id_to_idx[id] = len(self._ids)
            self._ids.append(id)
            if self._vectors is not None and self._vectors.shape[0] > 0:
                self._vectors = np.vstack([self._vectors, vector])
            else:
                self._vectors = vector

    def remove(self, ids: list[str]) -> None:
        if self._vectors is None:
            return

        for id_str in ids:
            if id_str in self._id_to_idx:
                del self._id_to_idx[id_str]
                try:
                    self._ids.remove(id_str)
                except ValueError:
                    pass

        # Rebuild vectors
        if self._ids:
            new_vecs = np.zeros((len(self._ids), self._dim), dtype=np.float32)
            for i, id_str in enumerate(self._ids):
                new_vecs[i] = self._vectors[self._id_to_idx[id_str]]
                self._id_to_idx[id_str] = i
            self._vectors = new_vecs
        else:
            self._vectors = np.empty((0, self._dim or 0), dtype=np.float32)

    def search(
        self, query: np.ndarray, top_k: int = 20
    ) -> list[tuple[str, float]]:
        if self._vectors is None or len(self._vectors) == 0:
            return []

        if query.ndim == 1:
            query = query.reshape(1, -1)
        query = self._normalize(query)

        # Cosine similarity = dot product (vectors are normalized)
        scores = np.dot(query, self._vectors.T)[0]  # (n,) float32

        if len(scores) <= top_k:
            top_indices = np.argsort(-scores)
        else:
            top_indices = np.argpartition(-scores, top_k)[:top_k]
            top_indices = top_indices[np.argsort(-scores[top_indices])]

        return [
            (self._ids[int(i)], float(scores[int(i)]))
            for i in top_indices[:top_k]
        ]

    def save(self, path: Path) -> None:
        data = {
            "dim": self._dim,
            "ids": self._ids,
            "vectors": self._vectors,
            "id_to_idx": self._id_to_idx,
        }
        path.write_bytes(pickle.dumps(data))

    def load(self, path: Path) -> None:
        data = pickle.loads(path.read_bytes())
        self._dim = data["dim"]
        self._ids = data["ids"]
        self._vectors = data["vectors"]
        self._id_to_idx = data["id_to_idx"]

    def rebuild(self) -> None:
        """Full rebuild from MetadataStore.

        This is called by EmbeddingIndex, which has access to MetadataStore.
        NumPyVectorIndex itself doesn't reference MetadataStore — the caller
        must provide the data.
        """
        # Actual rebuild logic lives in EmbeddingIndex.rebuild()
        # This is a no-op at the vector index level
        pass

    def stats(self) -> dict:
        mem = 0
        if self._vectors is not None:
            mem = self._vectors.nbytes
        return {
            "dim": self._dim or 0,
            "count": len(self._ids),
            "memory_bytes": mem,
            "memory_mb": round(mem / (1024 * 1024), 2),
        }

    def clear(self) -> None:
        self._ids = []
        self._vectors = np.empty((0, self._dim or 0), dtype=np.float32)
        self._id_to_idx = {}

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _normalize(vecs: np.ndarray) -> np.ndarray:
        """L2-normalize vectors in-place."""
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms
