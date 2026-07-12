"""RetrievalEngine — M7 Retrieval Engine facade.

Assembles all retrieval components:
  - BaseVectorIndex (NumPyVectorIndex by default)
  - EmbeddingIndex (bridges Store → VectorIndex)
  - EmbeddingWorker (async background embedding)
  - HybridRetriever (keyword + vector + recent)
  - Reranker (multi-dimensional second-pass ranking)
  - MemoryPlanner (task-aware retrieval planning)
  - RetrievalPipeline (pluggable stages)

Usage:
    engine = RetrievalEngine(
        store=memory_core.store,
        metadata=memory_core.metadata,
        events=memory_core.events,
    )
    engine.initialize()       # Build initial vector index, start worker
    results = engine.retrieve(RetrievalQuery(text="testing tools"))
    # Or: Planner → Retrieval
    results = engine.retrieve_for_task(TaskContext(current_query="add auth"))
"""

import time
from pathlib import Path

from src.memory.events import MemoryEvent, MemoryEventPayload
from src.memory.retrieval.config import RetrievalConfig
from src.memory.retrieval.embedding_index import EmbeddingIndex
from src.memory.retrieval.embedding_worker import EmbeddingWorker
from src.memory.retrieval.hybrid import HybridRetriever, WeightedSumFusion
from src.memory.retrieval.pipeline import (
    DeduplicateStage,
    FilterStage,
    FormatStage,
    RerankerStage,
    RetrievalPipeline,
    RetrieverStage,
)
from src.memory.retrieval.planner import MemoryPlanner, RetrievalIntent, TaskContext
from src.memory.retrieval.query import RetrievalQuery, RetrievalResult
from src.memory.retrieval.ranker import Reranker
from src.memory.retrieval.retriever import (
    KeywordRetriever,
    RecentRetriever,
    VectorRetriever,
)
from src.memory.retrieval.vector_index import BaseVectorIndex, NumPyVectorIndex


class RetrievalEngine:
    """M7 Retrieval Engine — semantic + keyword + recent memory search.

    Independent of M6's write Pipeline. Uses IndexManager + EventBus + MetadataStore
    to integrate without modifying any M6 code.

    Usage:
        engine = RetrievalEngine(store, metadata, events)
        engine.initialize()
        results = engine.retrieve(RetrievalQuery(text="..."))
    """

    def __init__(
        self,
        store,                # MemoryStore
        metadata,             # MetadataStore
        events,               # MemoryEventBus
        embedder=None,        # DenseEmbedder-compatible (auto-created if None)
        config: RetrievalConfig | None = None,
    ):
        self._store = store
        self._metadata = metadata
        self._events = events
        self._config = config or RetrievalConfig()

        # ── Embedder (reuse existing or create new) ──
        if embedder is not None:
            self._embedder = embedder
        else:
            from src.memory.retrieval.embedder import DenseEmbedder
            self._embedder = DenseEmbedder(model_name=self._config.model_name)
            # DenseEmbedder requires fit() before embed_query()
            # Fit with a dummy document to initialize the model
            self._embedder.fit(["initialize"])

        # ── Vector Index ──
        self.vector_index: BaseVectorIndex = NumPyVectorIndex()

        # ── Embedding Index ──
        self.embedding_index = EmbeddingIndex(
            vector_index=self.vector_index,
            embedder=self._embedder,
            metadata=self._metadata,
            store=self._store,
            sync_fallback=self._config.sync_fallback,
            embed_max_chars=self._config.embed_max_chars,
        )

        # ── Retrievers ──
        self.keyword_retriever = KeywordRetriever(store=self._store)
        self.vector_retriever = VectorRetriever(
            vector_index=self.vector_index,
            embedder=self._embedder,
            store=self._store,
        )
        self.recent_retriever = RecentRetriever(store=self._store)

        # ── Hybrid ──
        self.hybrid_retriever = HybridRetriever(
            retrievers=[
                self.keyword_retriever,
                self.vector_retriever,
                self.recent_retriever,
            ],
            config=self._config,
        )

        # ── Reranker ──
        self.reranker = Reranker(weights=self._config.rerank_weights)

        # ── Pipeline ──
        self.pipeline = RetrievalPipeline()
        self._register_default_stages()

        # ── Planner ──
        self.planner = MemoryPlanner(enabled=self._config.planner_enabled)

        # ── Worker ──
        self._worker: EmbeddingWorker | None = None
        if self._config.worker_enabled:
            self._worker = EmbeddingWorker(
                embedding_index=self.embedding_index,
                store=self._store,
                events=self._events,
                batch_size=self._config.worker_batch_size,
                flush_interval=self._config.worker_flush_interval,
                max_retries=self._config.worker_max_retries,
            )

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def initialize(self) -> "RetrievalEngine":
        """Initialize the engine: build vector index from existing memories, start worker.

        Call once after construction.
        """
        # Build initial vector index from existing active memories
        self.embedding_index.rebuild()

        # Register embedding index with store's IndexManager
        self._store.index.register(self.embedding_index)

        # Start worker
        if self._worker:
            self._worker.start()

        return self

    def shutdown(self) -> None:
        """Graceful shutdown: stop worker, save index."""
        if self._worker:
            self._worker.stop()

    # ═══════════════════════════════════════════════════════════
    # Retrieval
    # ═══════════════════════════════════════════════════════════

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        """Execute retrieval pipeline.

        Returns:
            Ranked, filtered, deduplicated results with final_score and entry populated.
        """
        results = self.pipeline.process(query, self._store)

        # M8: emit ACCESSED for each retrieved entry (drives ImportanceEngine)
        for r in results:
            self._events.emit(MemoryEventPayload(
                event=MemoryEvent.ACCESSED,
                entry_id=r.id,
                timestamp=time.time(),
                triggered_by="retrieval_engine",
            ))

        return results

    def retrieve_for_task(self, task_context: TaskContext) -> list[RetrievalResult]:
        """Planner → Retrieval: analyze task, generate intent, retrieve.

        This is the primary entry point for MemoryLayer.
        """
        intent = self.planner.plan(task_context)
        query = RetrievalQuery(
            text=intent.query_text,
            type_filter=intent.type_filter,
            tag_filter=intent.tag_filter,
            project_filter=intent.project_filter,
            min_importance=intent.min_importance,
            max_results=intent.max_results,
            channel_weights=intent.channel_weights,
        )
        return self.retrieve(query)

    # ═══════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════

    def save_index(self, path: Path) -> None:
        """Persist vector index to disk."""
        self.vector_index.save(path)

    def load_index(self, path: Path) -> None:
        """Restore vector index from disk."""
        self.vector_index.load(path)

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        return {
            "vector_index": self.vector_index.stats(),
            "worker": self._worker.stats if self._worker else {"running": False},
            "planner_enabled": self.planner.enabled,
            "pipeline_stages": self.pipeline.list_stages(),
        }

    # ═══════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════

    def _register_default_stages(self) -> None:
        """Register the 5 built-in retrieval pipeline stages."""
        self.pipeline.register_stage(RetrieverStage(self.hybrid_retriever))
        self.pipeline.register_stage(
            RerankerStage(self.reranker, max_candidates=self._config.max_rerank_candidates)
        )
        self.pipeline.register_stage(FilterStage())
        self.pipeline.register_stage(DeduplicateStage())
        self.pipeline.register_stage(FormatStage())
