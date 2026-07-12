"""M9 Memory Intelligence Layer — cognitive layer for Memory OS.

Components:
  - IntelligenceEngine  — facade, assembles all components
  - KnowledgeExtractor  — conversation → LLM → MemoryCandidate → Validator → Pipeline
  - ReflectionEngine    — scheduler for Merge/Conflict/Refine/Split strategies
  - TriggerPolicy       — pure event source (TASK_END, IDLE, MESSAGE_THRESHOLD, ...)
  - AsyncWorker         — background thread for LLM calls
  - PromptLoader        — load .md templates with variable substitution
  - ResponseParser      — raw dict → schema validation → dataclass
  - CandidateValidator  — validate MemoryCandidate before Pipeline ingestion
  - RelationType        — extensible enum for memory graph relationships

Core principle: LLM is the Proposer, NOT the Authority.
Every extracted memory goes through Validator → Pipeline → M8 ImportanceEngine.

Usage:
    from src.memory.intelligence import IntelligenceEngine, IntelligenceConfig

    engine = IntelligenceEngine(
        store=core.store,
        events=core.events,
        pipeline=core.pipeline,
        vector_index=retrieval_engine.vector_index,
        embedder=embedder,
        importance_engine=importance_engine,
        llm_call=llm_call,
    )
    engine.start()
    engine.track_message("User likes Python")
    engine.on_task_end()
    engine.stop()
"""

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

__all__ = [
    # Facade
    "IntelligenceEngine",
    "IntelligenceConfig",
    # Core
    "KnowledgeExtractor",
    "ReflectionEngine",
    # Trigger
    "TriggerPolicy",
    "TriggerEvent",
    "TriggerPayload",
    # Infrastructure
    "AsyncWorker",
    "PromptLoader",
    "ResponseParser",
    "CandidateValidator",
    # Data
    "MemoryCandidate",
    "ExtractionResult",
    "ReflectionResult",
    "StrategyResult",
    "RelationType",
    # Strategies
    "ReflectionStrategy",
    "MergeStrategy",
    "ConflictStrategy",
    "RefineStrategy",
    "SplitStrategy",
]
