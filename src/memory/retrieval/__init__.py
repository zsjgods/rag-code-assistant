"""M7 Retrieval Engine — semantic + keyword + recent memory retrieval.

Independent of M6. Uses IndexManager + EventBus + MetadataStore for integration.
"""

from src.memory.retrieval.config import RetrievalConfig, RerankWeights
from src.memory.retrieval.embedding_index import EmbeddingIndex
from src.memory.retrieval.embedding_worker import EmbeddingWorker
from src.memory.retrieval.engine import RetrievalEngine
from src.memory.retrieval.hybrid import (
    HybridFusion,
    HybridRetriever,
    ReciprocalRankFusion,
    WeightedSumFusion,
)
from src.memory.retrieval.pipeline import (
    DeduplicateStage,
    FilterStage,
    FormatStage,
    RerankerStage,
    RetrievalPipeline,
    RetrievalStage,
    RetrieverStage,
)
from src.memory.retrieval.planner import MemoryPlanner, RetrievalIntent, TaskContext
from src.memory.retrieval.query import RetrievalQuery, RetrievalResult
from src.memory.retrieval.ranker import Reranker
from src.memory.retrieval.retriever import (
    KeywordRetriever,
    RecentRetriever,
    Retriever,
    VectorRetriever,
)
from src.memory.retrieval.vector_index import BaseVectorIndex, NumPyVectorIndex

__all__ = [
    # Engine
    "RetrievalEngine",
    # Config
    "RetrievalConfig",
    "RerankWeights",
    # Vector Index
    "BaseVectorIndex",
    "NumPyVectorIndex",
    # Embedding
    "EmbeddingIndex",
    "EmbeddingWorker",
    # Retrievers
    "Retriever",
    "KeywordRetriever",
    "VectorRetriever",
    "RecentRetriever",
    # Hybrid
    "HybridRetriever",
    "HybridFusion",
    "WeightedSumFusion",
    "ReciprocalRankFusion",
    # Pipeline
    "RetrievalPipeline",
    "RetrievalStage",
    "RetrieverStage",
    "RerankerStage",
    "FilterStage",
    "DeduplicateStage",
    "FormatStage",
    # Reranker
    "Reranker",
    # Planner
    "MemoryPlanner",
    "TaskContext",
    "RetrievalIntent",
    # Query
    "RetrievalQuery",
    "RetrievalResult",
]
