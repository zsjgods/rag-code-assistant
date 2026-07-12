"""LifecycleEngine — M10 Memory Lifecycle & Operations facade.

Assembles:
  - LifecyclePolicyEngine  — unified policy management
  - LifecycleStateMachine  — weighted state transitions
  - ArchiveEngine          — policy-driven auto-archiving
  - MemoryCompressor       — RuleBased/LLM/Hybrid group compression
  - GarbageCollector       — Clean/Validate/Repair (NO purge)
  - LifecycleWorker        — background periodic scheduler
  - LifecycleMetricsCollector — health dashboard

Usage:
    engine = LifecycleEngine(
        store=core.store,
        lifecycle_manager=core.store._lifecycle,  # M6 LifecycleManager
        events=core.events,
        vector_index=retrieval_engine.vector_index,
        embedder=embedder,
        llm_call=llm_call,
    )
    engine.start()   # Start background scheduler
    engine.stop()
"""

import time

from src.memory.events import MemoryEventBus
from src.memory.lifecycle.archiver import ArchiveEngine
from src.memory.lifecycle.compressor import MemoryCompressor
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.gc import GarbageCollector
from src.memory.lifecycle.metrics import LifecycleMetrics, LifecycleMetricsCollector
from src.memory.lifecycle.policy import LifecyclePolicyEngine
from src.memory.lifecycle.state import LifecycleStateMachine
from src.memory.lifecycle.worker import LifecycleWorker


class LifecycleEngine:
    """M10 Memory Lifecycle & Operations Engine.

    Wires together state machine, archiver, compressor, GC, and scheduler.
    All policies managed by LifecyclePolicyEngine — fully configurable.
    """

    def __init__(
        self,
        store,                     # MemoryStore
        lifecycle_manager,         # LifecycleManager (M6)
        events: MemoryEventBus,
        vector_index=None,         # BaseVectorIndex (M7)
        embedder=None,             # DenseEmbedder
        llm_call=None,             # Callable[[str], str]
        prompt_loader=None,        # PromptLoader (M9)
        config: LifecycleConfig | None = None,
    ):
        self._store = store
        self._lifecycle_mgr = lifecycle_manager
        self._events = events
        self._config = config or LifecycleConfig()

        # ── Policy Engine (unified) ──
        self.policy = LifecyclePolicyEngine(self._config)

        # ── State Machine ──
        self.state_machine = LifecycleStateMachine(
            store=self._store,
            lifecycle_manager=self._lifecycle_mgr,
            events=self._events,
            config=self._config,
        )

        # ── Archive Engine ──
        self.archiver = ArchiveEngine(
            store=self._store,
            lifecycle_manager=self._lifecycle_mgr,
            events=self._events,
            access_tracker=self.state_machine,  # Share access tracker
            config=self._config,
        )

        # ── Memory Compressor ──
        self.compressor = MemoryCompressor(
            store=self._store,
            events=self._events,
            vector_index=vector_index,
            embedder=embedder,
            llm_call=llm_call,
            prompt_loader=prompt_loader,
            config=self._config,
        )

        # ── Garbage Collector ──
        self.gc = GarbageCollector(
            store=self._store,
            events=self._events,
            config=self._config,
        )

        # ── Metrics ──
        self.metrics_collector = LifecycleMetricsCollector(
            store=self._store,
            state_machine=self.state_machine,
            archiver=self.archiver,
            compressor=self.compressor,
            gc=self.gc,
        )

        # ── Worker ──
        self.worker = LifecycleWorker(
            cycle_fn=self._run_cycle,
            config=self._config,
        )

        self._started = False

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Start the background lifecycle scheduler."""
        if self._started:
            return
        self.worker.start()
        self._started = True

    def stop(self) -> None:
        """Stop the background scheduler."""
        self.worker.stop()
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    # ═══════════════════════════════════════════════════════════
    # Manual API
    # ═══════════════════════════════════════════════════════════

    def archive(self, entry_id: str) -> bool:
        """Manually archive an entry."""
        from src.memory.identity import MemoryID
        result = self.archiver.archive_one(MemoryID(entry_id))
        if result:
            self.metrics_collector.record_archive()
        return result

    def restore(self, entry_id: str) -> bool:
        """Restore an archived entry."""
        from src.memory.identity import MemoryID
        result = self.archiver.restore(MemoryID(entry_id))
        if result:
            self.metrics_collector.record_restore()
        return result

    def compress_now(self) -> list[str]:
        """Manually trigger compression."""
        result = self.compressor.schedule()
        for _ in result:
            self.metrics_collector.record_compression()
        return result

    def run_gc(self):
        """Manually trigger garbage collection."""
        result = self.gc.collect()
        self.metrics_collector.record_gc()
        return result

    def metrics(self) -> LifecycleMetrics:
        """Get current health metrics."""
        return self.metrics_collector.collect()

    def run_cycle(self):
        """Run a full lifecycle cycle (state → archive → compress → GC)."""
        self._run_cycle()

    # ═══════════════════════════════════════════════════════════
    # Internal cycle
    # ═══════════════════════════════════════════════════════════

    def _run_cycle(self) -> None:
        """One complete lifecycle check cycle."""
        # 1. State evaluation + transitions
        state_counts = self.state_machine.evaluate_all()

        # 2. Archive candidates
        archived = self.archiver.schedule()
        for _ in archived:
            self.metrics_collector.record_archive()

        # 3. Compression
        compressed = self.compressor.schedule()
        for _ in compressed:
            self.metrics_collector.record_compression()

        # 4. Garbage Collection
        self.gc.collect()
        self.metrics_collector.record_gc()

        # Record cycle completion
        self.metrics_collector.record_cycle()

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        return {
            "running": self.is_running,
            "worker": self.worker.stats(),
            "state_machine": self.state_machine.stats(),
            "archiver": self.archiver.stats(),
            "compressor": self.compressor.stats(),
            "gc": self.gc.stats(),
        }
