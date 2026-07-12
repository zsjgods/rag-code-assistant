"""EmbeddingIndex — bridges MemoryStore events to BaseVectorIndex.

Registers as a standard M6 Index. Listens to create/update/delete events
and keeps the vector index in sync.

Two modes:
  - Async (default): emits events → EmbeddingWorker picks them up
  - Sync fallback: embeds immediately in on_create/on_update (if Worker not running)
"""

import time

import numpy as np

from src.memory.events import MemoryEvent, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.index import Index
from src.memory.types import MemoryEntry


class EmbeddingIndex(Index):
    """Index that maintains a vector index for semantic search.

    Usage:
        emb_idx = EmbeddingIndex(
            vector_index=NumPyVectorIndex(),
            embedder=DenseEmbedder(),
            metadata=memory_core.metadata,
            store=memory_core.store,
            sync_fallback=False,  # Let Worker handle embedding
        )
        memory_core.store.index.register(emb_idx)
    """

    name = "embedding"

    def __init__(
        self,
        vector_index,        # BaseVectorIndex
        embedder,            # DenseEmbedder-compatible
        metadata,            # MetadataStore
        store,               # MemoryStore (for access to all entries during rebuild)
        sync_fallback: bool = False,
        embed_max_chars: int = 500,
    ):
        self._vector_index = vector_index
        self._embedder = embedder
        self._metadata = metadata
        self._store = store
        self._sync_fallback = sync_fallback
        self._embed_max_chars = embed_max_chars

    # ═══════════════════════════════════════════════════════════
    # Index interface
    # ═══════════════════════════════════════════════════════════

    def on_create(self, entry: MemoryEntry) -> None:
        if self._sync_fallback:
            self.embed_and_index(entry)
        # Async mode: Worker picks up via MemoryEvent.CREATED

    def on_update(self, entry: MemoryEntry, changes: dict) -> None:
        # Only re-embed if content changed
        if not self._content_changed(changes):
            return

        if self._sync_fallback:
            self.embed_and_index(entry)
        # Async mode: Worker picks up via MemoryEvent.UPDATED

    def on_delete(self, entry_id: MemoryID) -> None:
        self._vector_index.remove([entry_id.value])
        self._metadata.delete(entry_id)

    def clear(self) -> None:
        self._vector_index.clear()

    # ═══════════════════════════════════════════════════════════
    # Embedding
    # ═══════════════════════════════════════════════════════════

    def embed_and_index(self, entry: MemoryEntry) -> None:
        """Embed entry content and add/update the vector index. Synchronous."""
        text = self._extract_text(entry)
        if not text.strip():
            return

        try:
            vec = self._embedder.embed_query(text)  # → (dim,) float32
            self._vector_index.update(entry.id_str, vec)
            self._metadata.set(entry.id, "embedding", vec.tolist())
        except Exception:
            pass  # Best-effort: one bad entry shouldn't break the index

    def embed_batch(self, entries: list[MemoryEntry]) -> int:
        """Batch embed multiple entries (used by Worker and rebuild).

        Returns count of successfully embedded entries.
        """
        if not entries:
            return 0

        texts = [self._extract_text(e) for e in entries]
        ids = [e.id_str for e in entries]

        # Filter empty texts
        valid = [(i, t) for i, t in zip(ids, texts) if t.strip()]
        if not valid:
            return 0

        try:
            valid_ids = [v[0] for v in valid]
            valid_texts = [v[1] for v in valid]
            vecs = self._embedder.embed_chunks(valid_texts)  # → (n, dim) float32
            self._vector_index.add(valid_ids, vecs)
            for i, id_str in enumerate(valid_ids):
                self._metadata.set(MemoryID(id_str), "embedding", vecs[i].tolist())
            return len(valid_ids)
        except Exception:
            return 0

    # ═══════════════════════════════════════════════════════════
    # Rebuild
    # ═══════════════════════════════════════════════════════════

    def rebuild(self) -> int:
        """Full rebuild from MemoryStore: re-embed all active entries.

        Returns count of re-embedded entries.
        """
        self._vector_index.clear()
        active = list(self._store.get_active().values())
        return self.embed_batch(active)

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _extract_text(self, entry: MemoryEntry) -> str:
        """Extract text for embedding from summary + truncated content."""
        summary = entry.content.summary or ""
        text = entry.content.text or ""
        if len(text) > self._embed_max_chars:
            text = text[:self._embed_max_chars]
        return (summary + " " + text).strip()

    @staticmethod
    def _content_changed(changes: dict) -> bool:
        """Check if any content-related field changed."""
        content_keys = {"content.text", "content.summary", "content.tags"}
        for key in changes:
            if key in content_keys:
                return True
            # Also match prefix "content."
            if key.startswith("content."):
                return True
        return False
