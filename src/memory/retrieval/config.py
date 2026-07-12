"""RetrievalConfig — all tunable parameters for M7 Retrieval Engine."""

from dataclasses import dataclass, field


@dataclass
class RerankWeights:
    """Weights for multi-dimensional scoring in Reranker.

    final_score = relevance^α × importance^β × freshness^γ × frequency^δ
    """

    relevance: float = 1.0  # Cosine similarity / keyword score
    importance: float = 0.5  # MemoryScore.importance
    freshness: float = 0.3  # MemoryScore.freshness (1→0 decay)
    frequency: float = 0.1  # MemoryScore.frequency (access count)


@dataclass
class RetrievalConfig:
    """All tunable parameters for the M7 Retrieval Engine.

    Usage:
        config = RetrievalConfig()
        config.channel_weights["keyword"] = 0.4

        engine = RetrievalEngine(store, metadata, events, embedder, config=config)
    """

    # ── Embedding ──
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embed_text_fields: list[str] = field(default_factory=lambda: ["summary", "text"])
    embed_max_chars: int = 500  # Truncate text for embedding

    # ── EmbeddingIndex ──
    sync_fallback: bool = False  # If True, embed synchronously when Worker not running

    # ── Hybrid Fusion ──
    fusion_strategy: str = "weighted_sum"  # "weighted_sum" | "rrf"
    channel_weights: dict[str, float] = field(default_factory=lambda: {
        "keyword": 0.3,
        "vector": 0.5,
        "recent": 0.2,
    })
    rrf_k: int = 60  # Reciprocal Rank Fusion constant

    # ── Reranker ──
    rerank_weights: RerankWeights = field(default_factory=RerankWeights)

    # ── Embedding Worker ──
    worker_enabled: bool = True
    worker_batch_size: int = 10
    worker_flush_interval: float = 1.0  # Seconds
    worker_max_retries: int = 3

    # ── Planner ──
    planner_enabled: bool = True
    planner_max_recent_messages: int = 3  # Recent conversation rounds to consider

    # ── Limits ──
    max_hybrid_candidates: int = 50  # Max candidates per channel before fusion
    max_rerank_candidates: int = 25  # Max candidates Reranker processes
