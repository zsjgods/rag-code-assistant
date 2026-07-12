"""Memory Core — enterprise-grade memory kernel for Agent OS.

10 subsystems, each with a single responsibility:

  Store       — Pure CRUD + 3-pool + persistence
  Registry    — MemoryType registration center + plugin support
  Schema      — Validate, serialize, deserialize, migrate
  Identity    — MemoryID, UserID, ProjectID, WorkspaceID, SessionID, AgentID
  Metadata    — Decoupled key-value extension data
  Index       — Pluggable indexes (type, tag, project, owner, state)
  Pipeline    — Pluggable processing pipeline for inbound entries
  Policy      — Rule-based policy engine
  Lifecycle   — State transitions (archive, recover, delete, purge, snapshot)
  EventBus    — Publish/subscribe for memory events

All subsystems are assembled by MemoryCore (the facade). External code interacts
with MemoryCore, NOT with individual subsystems directly.

Usage:
    from src.memory import MemoryCore

    core = MemoryCore(db_path=Path(".memory"))
    core.store.load()  # Restore from disk

    # Add a memory through the pipeline
    entry = MemoryEntry.create(text="Use pytest for testing", type=MemoryType.TOOL)
    ok, reason, result = core.pipeline.process(entry, core.store)
"""

from pathlib import Path

from src.memory.events import MemoryEventBus, MemoryEvent, MemoryEventPayload, memory_events
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
from src.memory.retrieval.pipeline import RetrievalPipeline
from src.memory.retrieval.planner import MemoryPlanner, RetrievalIntent, TaskContext
from src.memory.retrieval.query import RetrievalQuery, RetrievalResult
from src.memory.retrieval.ranker import Reranker
from src.memory.retrieval.retriever import (
    KeywordRetriever,
    RecentRetriever,
    VectorRetriever,
)
from src.memory.retrieval.vector_index import BaseVectorIndex, NumPyVectorIndex
from src.memory.importance.config import ImportanceConfig
from src.memory.importance.decay import FreshnessDecay
from src.memory.importance.engine import ImportanceEngine
from src.memory.importance.feedback import FeedbackHandler
from src.memory.importance.scoring import ImportanceScorer
from src.memory.importance.tracking import AccessTracker
from src.memory.importance.vacuum import VacuumPolicy
from src.memory.intelligence.candidate import (
    ExtractionResult,
    MemoryCandidate,
    ReflectionResult,
    StrategyResult,
)
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.engine import IntelligenceEngine
from src.memory.intelligence.extractor import KnowledgeExtractor
from src.memory.intelligence.parser import ResponseParser
from src.memory.intelligence.prompt_loader import PromptLoader
from src.memory.intelligence.reflector import ReflectionEngine
from src.memory.intelligence.relation_types import RelationType
from src.memory.intelligence.strategies import (
    ConflictStrategy,
    MergeStrategy,
    RefineStrategy,
    ReflectionStrategy,
    SplitStrategy,
)
from src.memory.intelligence.trigger import TriggerEvent, TriggerPayload, TriggerPolicy
from src.memory.intelligence.validator import CandidateValidator
from src.memory.intelligence.worker import AsyncWorker
from src.memory.lifecycle.archiver import ArchiveEngine as LifecycleArchiveEngine
from src.memory.lifecycle.compressor import (
    CompressionStrategy,
    HybridCompression,
    LLMCompression,
    MemoryCompressor,
    RuleBasedCompression,
)
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.engine import LifecycleEngine
from src.memory.lifecycle.gc import GCResult, GarbageCollector
from src.memory.lifecycle.metrics import LifecycleMetrics, LifecycleMetricsCollector
from src.memory.lifecycle.policy import (
    ArchivePolicy,
    CompressionPolicy,
    LifecyclePolicyEngine,
    RetentionPolicy,
    StateTransitionPolicy,
)
from src.memory.lifecycle.state import LifecycleStateMachine
from src.memory.lifecycle.worker import LifecycleWorker
from src.memory.identity import (
    AgentID,
    MemoryID,
    ProjectID,
    SessionID,
    UserID,
    WorkspaceID,
)
from src.memory.index import (
    Index,
    IndexManager,
    OwnerIndex,
    ProjectIndex,
    StateIndex,
    TagIndex,
    TypeIndex,
)
from src.memory.lifecycle.manager import LifecycleManager
from src.memory.metadata import MemoryMetadata, MetadataStore
from src.memory.pipeline import (
    DeduplicateStage,
    MemoryPipeline,
    NormalizeStage,
    PersistStage,
    PipelineStage,
    PolicyCheckStage,
    SchemaStage,
)
from src.memory.policy import (
    ContentLengthRule,
    ContentPatternRule,
    DuplicateRule,
    PolicyEngine,
    PolicyRule,
    ScopeLimitRule,
    SourceRule,
    TypeAllowRule,
    TypeLimitRule,
)
from src.memory.registry import (
    BUILTIN_TYPES,
    MemoryPlugin,
    MemoryRegistry,
    MemoryTypeDefinition,
)
from src.memory.schema import SchemaLayer, SchemaResult
from src.memory.store import MemoryStore
from src.memory.types import (
    MemoryContent,
    MemoryEntry,
    MemoryIdentity,
    MemoryOwnership,
    MemoryRelation,
    MemoryScope,
    MemoryScore,
    MemoryState,
    MemoryType,
    MemoryVersion,
    MemoryVisibility,
)


class MemoryCore:
    """Memory OS kernel facade.

    Assembles all 10 subsystems and provides a unified interface.
    External code (main.py, tools, etc.) interacts with MemoryCore,
    NOT with individual subsystems.

    Usage:
        core = MemoryCore(db_path=Path(".memory"))
        core.load()  # Restore from disk

        # Add a memory
        entry = MemoryEntry.create(text="Something important", type=MemoryType.KNOWLEDGE)
        ok, reason, result = core.add(entry)

        # Get memories
        entry = core.get(MemoryID("abc123"))

        # Persist
        core.save()
    """

    def __init__(self, db_path: str | Path, strict_schema: bool = False):
        """Initialize the Memory Core with all subsystems.

        Args:
            db_path: Directory for persistence file (memory.json).
            strict_schema: If True, schema warnings become errors.
        """
        self.db_path = Path(db_path)

        # ── Subsystems (in dependency order) ──
        self.events = MemoryEventBus()
        self.schema = SchemaLayer(strict=strict_schema)
        self.registry = MemoryRegistry()
        self.metadata = MetadataStore()

        # Policy engine
        self.policy = PolicyEngine()
        self._register_default_policy_rules()

        # Store
        self.store = MemoryStore(
            db_path=self.db_path,
            schema=self.schema,
            events=self.events,
        )

        # Pipeline
        self.pipeline = MemoryPipeline()
        self._register_default_pipeline_stages()

        # ── M7: Retrieval Engine (lazy-initialized) ──
        self._retrieval_engine = None  # Created on first access

        # ── M8: Importance Engine (lazy-initialized) ──
        self._importance_engine = None  # Created on first access

        # ── M9: Intelligence Engine (lazy-initialized) ──
        self._intelligence_engine = None  # Created on first access

        # ── M10: Lifecycle Engine (lazy-initialized) ──
        self._lifecycle_engine = None  # Created on first access

    # ── Convenience methods (delegate to store + pipeline) ──

    def add(self, entry: MemoryEntry) -> tuple[bool, str, MemoryEntry | None]:
        """Add a memory through the pipeline (includes persist).

        Returns:
            (accepted, reason, final_entry_or_None)
        """
        ok, reason, result = self.pipeline.process(entry, self.store)
        if ok and result is not None:
            self.save()
        return ok, reason, result

    def get(self, entry_id: MemoryID) -> MemoryEntry | None:
        """Read a memory by ID."""
        return self.store.read(entry_id)

    def update(self, entry_id: MemoryID, **fields) -> bool:
        """Update a memory's fields."""
        return self.store.update(entry_id, **fields)

    def delete(self, entry_id: MemoryID) -> bool:
        """Soft-delete a memory."""
        return self.store.delete(entry_id)

    def archive(self, entry_id: MemoryID) -> bool:
        """Archive a memory."""
        return self.store.archive(entry_id)

    def recover(self, entry_id: MemoryID) -> bool:
        """Recover an archived/deleted memory."""
        return self.store.recover(entry_id)

    def purge(self, entry_id: MemoryID) -> bool:
        """Permanently delete a memory."""
        return self.store.purge(entry_id)

    # ── Persistence ──

    def save(self) -> None:
        """Persist all memories to disk."""
        self.store.save()

    def load(self) -> int:
        """Load memories from disk. Returns count loaded."""
        return self.store.load()

    # ── Stats ──

    def stats(self) -> dict:
        """Return store statistics."""
        return self.store.stats()

    @property
    def active_count(self) -> int:
        return len(self.store.get_active())

    # ── M7: Retrieval Engine ──

    @property
    def retrieval(self):
        """Access the RetrievalEngine (M7). Lazy-initialized."""
        return self._retrieval_engine

    def init_retrieval(self, config=None) -> "RetrievalEngine":
        """Initialize the M7 Retrieval Engine.

        Must be called after MemoryCore construction to enable semantic search.
        """
        from src.memory.retrieval import RetrievalEngine, RetrievalConfig
        self._retrieval_engine = RetrievalEngine(
            store=self.store,
            metadata=self.metadata,
            events=self.events,
            config=config,
        )
        self._retrieval_engine.initialize()
        return self._retrieval_engine

    # ── M8: Importance Engine ──

    @property
    def importance(self):
        """Access the ImportanceEngine (M8). Lazy-initialized."""
        return self._importance_engine

    def init_importance(self, config=None) -> "ImportanceEngine":
        """Initialize the M8 Importance Engine.

        Must be called after MemoryCore construction to enable dynamic scoring.
        Should be called AFTER init_retrieval() so ACCESSED events are flowing.
        """
        from src.memory.importance import ImportanceEngine, ImportanceConfig
        self._importance_engine = ImportanceEngine(
            store=self.store,
            events=self.events,
            config=config,
        )
        self._importance_engine.start()
        return self._importance_engine

    # ── M9: Intelligence Engine ──

    @property
    def intelligence(self):
        """Access the IntelligenceEngine (M9). Lazy-initialized."""
        return self._intelligence_engine

    def init_intelligence(
        self,
        llm_call=None,
        config=None,
    ) -> "IntelligenceEngine":
        """Initialize the M9 Intelligence Engine.

        Must be called after MemoryCore construction to enable auto-learning.
        Should be called AFTER init_retrieval() (for vector_index) and
        init_importance() (for importance recalculation).

        Args:
            llm_call: Callable[[str], str] for LLM calls.
            config: IntelligenceConfig instance (optional).
        """
        from src.memory.intelligence import IntelligenceEngine, IntelligenceConfig
        self._intelligence_engine = IntelligenceEngine(
            store=self.store,
            events=self.events,
            pipeline=self.pipeline,
            vector_index=self._retrieval_engine.vector_index if self._retrieval_engine else None,
            embedder=self._retrieval_engine._embedder if self._retrieval_engine else None,
            importance_engine=self._importance_engine,
            llm_call=llm_call,
            config=config,
        )
        self._intelligence_engine.start()
        return self._intelligence_engine

    # ── M10: Lifecycle Engine ──

    @property
    def lifecycle(self):
        """Access the LifecycleEngine (M10). Lazy-initialized."""
        return self._lifecycle_engine

    def init_lifecycle(
        self,
        llm_call=None,
        config=None,
    ) -> "LifecycleEngine":
        """Initialize the M10 Lifecycle Engine.

        Must be called after MemoryCore construction. Should be called
        AFTER init_retrieval() (for vector_index).

        Args:
            llm_call: Callable[[str], str] for LLM compression (optional).
            config: LifecycleConfig instance (optional).
        """
        from src.memory.lifecycle import LifecycleEngine, LifecycleConfig
        self._lifecycle_engine = LifecycleEngine(
            store=self.store,
            lifecycle_manager=self.store._lifecycle,
            events=self.events,
            vector_index=self._retrieval_engine.vector_index if self._retrieval_engine else None,
            embedder=self._retrieval_engine._embedder if self._retrieval_engine else None,
            llm_call=llm_call,
            config=config,
        )
        self._lifecycle_engine.start()
        return self._lifecycle_engine

    # ── Internal wiring ──

    def _register_default_pipeline_stages(self) -> None:
        """Register the 5 built-in pipeline stages, including persist."""
        policy_check = PolicyCheckStage()
        policy_check.set_engine(self.policy)

        self.pipeline.register_stage(SchemaStage(self.schema))
        self.pipeline.register_stage(NormalizeStage())
        self.pipeline.register_stage(DeduplicateStage(), after="normalize")
        self.pipeline.register_stage(policy_check, after="deduplicate")
        self.pipeline.register_stage(PersistStage())  # Always last

    def _register_default_policy_rules(self) -> None:
        """Register the 7 built-in policy rules."""
        self.policy.register_rule(TypeAllowRule())          # Allow all types by default
        self.policy.register_rule(ContentPatternRule())     # No forbidden patterns by default
        self.policy.register_rule(ContentLengthRule(min_length=1, max_length=50000))
        self.policy.register_rule(DuplicateRule(allow_duplicates=False))
        self.policy.register_rule(ScopeLimitRule())         # No scope limits by default
        self.policy.register_rule(TypeLimitRule())          # No type limits by default
        self.policy.register_rule(SourceRule())             # Allow all sources by default


# ── Public API ──
__all__ = [
    # Facade
    "MemoryCore",
    # Store
    "MemoryStore",
    # Types
    "MemoryEntry",
    "MemoryIdentity",
    "MemoryContent",
    "MemoryOwnership",
    "MemoryScore",
    "MemoryRelation",
    "MemoryVersion",
    "MemoryType",
    "MemoryState",
    "MemoryScope",
    "MemoryVisibility",
    # Identity
    "MemoryID",
    "UserID",
    "ProjectID",
    "WorkspaceID",
    "SessionID",
    "AgentID",
    # Schema
    "SchemaLayer",
    "SchemaResult",
    # Registry
    "MemoryRegistry",
    "MemoryTypeDefinition",
    "MemoryPlugin",
    "BUILTIN_TYPES",
    # Index
    "IndexManager",
    "Index",
    "TypeIndex",
    "TagIndex",
    "ProjectIndex",
    "OwnerIndex",
    "StateIndex",
    # Pipeline
    "MemoryPipeline",
    "PipelineStage",
    "SchemaStage",
    "NormalizeStage",
    "DeduplicateStage",
    "PolicyCheckStage",
    "PersistStage",
    # Policy
    "PolicyEngine",
    "PolicyRule",
    "TypeAllowRule",
    "ContentLengthRule",
    "ContentPatternRule",
    "DuplicateRule",
    "ScopeLimitRule",
    "TypeLimitRule",
    "SourceRule",
    # Lifecycle
    "LifecycleManager",
    # Metadata
    "MemoryMetadata",
    "MetadataStore",
    # Events
    "MemoryEventBus",
    "MemoryEvent",
    "MemoryEventPayload",
    "memory_events",
    # M7 Retrieval
    "RetrievalEngine",
    "RetrievalConfig",
    "BaseVectorIndex",
    "NumPyVectorIndex",
    "EmbeddingIndex",
    "EmbeddingWorker",
    "RetrievalQuery",
    "RetrievalResult",
    "KeywordRetriever",
    "VectorRetriever",
    "RecentRetriever",
    "HybridRetriever",
    "HybridFusion",
    "WeightedSumFusion",
    "ReciprocalRankFusion",
    "RetrievalPipeline",
    "Reranker",
    "RerankWeights",
    "MemoryPlanner",
    "TaskContext",
    "RetrievalIntent",
    # M8 Importance
    "ImportanceEngine",
    "ImportanceConfig",
    "ImportanceScorer",
    "FreshnessDecay",
    "AccessTracker",
    "FeedbackHandler",
    "VacuumPolicy",
    # M9 Intelligence
    "IntelligenceEngine",
    "IntelligenceConfig",
    "KnowledgeExtractor",
    "ReflectionEngine",
    "TriggerPolicy",
    "TriggerEvent",
    "TriggerPayload",
    "AsyncWorker",
    "PromptLoader",
    "ResponseParser",
    "CandidateValidator",
    "MemoryCandidate",
    "ExtractionResult",
    "ReflectionResult",
    "StrategyResult",
    "RelationType",
    "ReflectionStrategy",
    "MergeStrategy",
    "ConflictStrategy",
    "RefineStrategy",
    "SplitStrategy",
    # M10 Lifecycle
    "LifecycleEngine",
    "LifecycleConfig",
    "LifecyclePolicyEngine",
    "StateTransitionPolicy",
    "ArchivePolicy",
    "CompressionPolicy",
    "RetentionPolicy",
    "LifecycleStateMachine",
    "MemoryCompressor",
    "CompressionStrategy",
    "RuleBasedCompression",
    "LLMCompression",
    "HybridCompression",
    "GarbageCollector",
    "GCResult",
    "LifecycleWorker",
    "LifecycleMetrics",
    "LifecycleMetricsCollector",
]
