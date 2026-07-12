"""Memory Lifecycle — state transitions, archive, compression, GC.

M6: LifecycleManager (3-pool: active/archived/deleted)
M10: LifecycleEngine (5-state: active/warm/cold/archived/deleted)
       + ArchiveEngine + MemoryCompressor + GarbageCollector
       + PolicyEngine + LifecycleMetrics
"""

from src.memory.lifecycle.archiver import ArchiveEngine
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
from src.memory.lifecycle.manager import LifecycleManager, LifecycleStats
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

__all__ = [
    # M6 (re-export)
    "LifecycleManager",
    "LifecycleStats",
    # M10
    "LifecycleEngine",
    "LifecycleConfig",
    "LifecyclePolicyEngine",
    "StateTransitionPolicy",
    "ArchivePolicy",
    "CompressionPolicy",
    "RetentionPolicy",
    "LifecycleStateMachine",
    "ArchiveEngine",
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
