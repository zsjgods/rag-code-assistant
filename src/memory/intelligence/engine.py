"""IntelligenceEngine — M9 Memory Intelligence Layer facade.

Assembles:
  - TriggerPolicy      — pure event source (TASK_END, IDLE, MESSAGE_THRESHOLD, ...)
  - KnowledgeExtractor — conversation → LLM → MemoryCandidate → Validator → Pipeline
  - ReflectionEngine   — scheduler for Merge/Conflict/Refine/Split strategies
  - AsyncWorker        — background thread for LLM calls

LLM is the Proposer, NOT the Authority. Every extracted memory goes through
Validator → Pipeline → M8 ImportanceEngine before becoming a real MemoryEntry.

Usage:
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
    # ... agent loop runs, trigger events fire ...
    engine.stop()
"""

from collections.abc import Callable

from src.memory.events import MemoryEvent, MemoryEventBus
from src.memory.identity import MemoryID
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.extractor import KnowledgeExtractor
from src.memory.intelligence.reflector import ReflectionEngine
from src.memory.intelligence.strategies import (
    ConflictStrategy,
    MergeStrategy,
    RefineStrategy,
    SplitStrategy,
)
from src.memory.intelligence.trigger import TriggerEvent, TriggerPayload, TriggerPolicy
from src.memory.intelligence.worker import AsyncWorker


class IntelligenceEngine:
    """M9 Memory Intelligence Layer — cognitive layer for Memory OS.

    Wires together triggers, extraction, reflection, and async LLM worker.
    All components communicate via TriggerPolicy events — no direct coupling.
    """

    def __init__(
        self,
        store,                     # MemoryStore
        events: MemoryEventBus,
        pipeline,                  # MemoryPipeline
        vector_index=None,         # BaseVectorIndex | None
        embedder=None,             # DenseEmbedder | None
        importance_engine=None,    # ImportanceEngine (M8)
        llm_call: Callable[[str], str] | None = None,
        config: IntelligenceConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._pipeline = pipeline
        self._vector_index = vector_index
        self._embedder = embedder
        self._importance_engine = importance_engine
        self._llm_call = llm_call or (lambda x: x)  # No-op fallback
        self._config = config or IntelligenceConfig()

        # ── Trigger (pure event source) ──
        self.trigger = TriggerPolicy()
        self.trigger.configure(
            message_threshold=self._config.trigger_message_threshold,
            memory_threshold=self._config.trigger_memory_threshold,
            idle_seconds=self._config.trigger_idle_seconds,
            importance_spike=self._config.trigger_importance_spike,
        )

        # ── Extractor (subscribes to TASK_END + MESSAGE_THRESHOLD) ──
        self.extractor = KnowledgeExtractor(
            store=self._store,
            pipeline=self._pipeline,
            llm_call=self._llm_call,
            importance_engine=self._importance_engine,
            config=self._config,
        )

        # ── Reflection Engine (subscribes to MEMORY_THRESHOLD + IMPORTANCE_SPIKE) ──
        self.reflector = ReflectionEngine(
            store=self._store,
            events=self._events,
            vector_index=self._vector_index,
            embedder=self._embedder,
            llm_call=self._llm_call,
            config=self._config,
        )
        self._register_default_strategies()

        # ── Async Worker ──
        self.worker = AsyncWorker(
            process_fn=self._process_trigger_batch,
            config=self._config,
        )

        # ── Subscriptions ──
        self._unsubs: list[Callable[[], None]] = []
        self._started = False

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """Start all components and subscribe to trigger events."""
        if self._started:
            return

        # Wire trigger → extractor (TaskEnd + MessageThreshold)
        self._unsubs.append(
            self.trigger.subscribe(TriggerEvent.TASK_END, self._on_trigger)
        )
        self._unsubs.append(
            self.trigger.subscribe(TriggerEvent.MESSAGE_THRESHOLD, self._on_trigger)
        )

        # Wire trigger → reflector (MemoryThreshold + ImportanceSpike)
        self._unsubs.append(
            self.trigger.subscribe(TriggerEvent.MEMORY_THRESHOLD, self._on_trigger)
        )
        self._unsubs.append(
            self.trigger.subscribe(TriggerEvent.IMPORTANCE_SPIKE, self._on_trigger)
        )

        # Listen to M6 CREATED events to feed trigger
        self._unsubs.append(
            self._events.subscribe(MemoryEvent.CREATED, self._on_memory_created)
        )

        # Start background worker
        self.worker.start()

        self._started = True

    def stop(self) -> None:
        """Stop all components and unsubscribe."""
        self.worker.stop(drain=True)

        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()

        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    # ═══════════════════════════════════════════════════════════
    # Manual API (for tools)
    # ═══════════════════════════════════════════════════════════

    def extract_now(self, conversation_text: str | None = None):
        """Force immediate extraction. If no text given, uses buffered messages."""
        if conversation_text:
            return self.extractor.extract(conversation_text)
        elif self.extractor._conversation_buffer:
            text = "\n".join(self.extractor._conversation_buffer)
            self.extractor._conversation_buffer.clear()
            return self.extractor.extract(text)
        return None

    def reflect_now(self):
        """Force immediate reflection run."""
        return self.reflector.reflect()

    def list_conflicts(self) -> list[dict]:
        """List all active conflict relations."""
        conflicts = []
        for entry in self._store.get_active().values():
            for target_id, rel_type in entry.relation.related.items():
                if rel_type == "conflict":
                    target = self._store.read(MemoryID(target_id))
                    conflicts.append({
                        "entry_a": entry.id_str,
                        "entry_b": target_id,
                        "summary_a": entry.content.summary,
                        "summary_b": target.content.summary if target else "(not found)",
                    })
        return conflicts

    def resolve_conflict(self, entry_id: str, resolution: str) -> str:
        """Resolve a conflict: 'keep_a', 'keep_b', or 'keep_both'."""
        from src.memory.identity import MemoryID
        from src.memory.intelligence.relation_types import RelationType

        entry = self._store.read(MemoryID(entry_id))
        if entry is None:
            return f"Entry not found: {entry_id}"

        if resolution == "keep_both":
            # Remove conflict relation from both sides
            for target_id, rel_type in list(entry.relation.related.items()):
                if rel_type == RelationType.CONFLICT.value:
                    del entry.relation.related[target_id]
                    target = self._store.read(MemoryID(target_id))
                    if target:
                        target.relation.related.pop(entry.id_str, None)
            return f"Conflict resolved: both entries kept for {entry_id}"

        elif resolution == "keep_a":
            # Archive conflicting entries
            for target_id, rel_type in list(entry.relation.related.items()):
                if rel_type == RelationType.CONFLICT.value:
                    del entry.relation.related[target_id]
                    self._store.archive(MemoryID(target_id))
            return f"Conflict resolved: kept {entry_id}, archived conflicting entries"

        elif resolution == "keep_b":
            # Archive this entry, keep the conflicting ones
            self._store.archive(entry.id)
            return f"Conflict resolved: archived {entry_id}"

        return f"Unknown resolution: {resolution}"

    # ═══════════════════════════════════════════════════════════
    # Conversation tracking (called by agent loop)
    # ═══════════════════════════════════════════════════════════

    def track_message(self, text: str) -> None:
        """Track a conversation message. Feeds both trigger and extractor."""
        self.extractor.track_message(text)
        self.trigger.on_message(text)

    def on_task_end(self) -> None:
        """Signal task completion."""
        self.trigger.on_task_end()

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    def stats(self) -> dict:
        return {
            "running": self.is_running,
            "extractor": self.extractor.stats(),
            "reflector": self.reflector.stats(),
            "worker": self.worker.stats(),
            "trigger_message_count": self.trigger._message_count,
        }

    # ═══════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════

    def _register_default_strategies(self) -> None:
        """Register the 4 built-in reflection strategies."""
        self.reflector.register_strategy(MergeStrategy())
        self.reflector.register_strategy(ConflictStrategy())
        self.reflector.register_strategy(RefineStrategy())
        self.reflector.register_strategy(SplitStrategy())

    def _on_trigger(self, payload: TriggerPayload) -> None:
        """Route trigger events to the async worker for batch processing."""
        self.worker.enqueue(payload)

    def _on_memory_created(self, payload) -> None:
        """Listen to M6 CREATED events; feed trigger for MEMORY_THRESHOLD."""
        entry = self._store.read(MemoryID(payload.entry_id))
        importance = entry.score.importance if entry else 0.5
        self.trigger.on_memory_created(importance)

    def _process_trigger_batch(self, batch: list[TriggerPayload]) -> None:
        """Process a batch of trigger events (called by AsyncWorker).

        Routes each event to the appropriate handler:
          - TASK_END / MESSAGE_THRESHOLD → extractor
          - MEMORY_THRESHOLD / IMPORTANCE_SPIKE → reflector
        """
        for payload in batch:
            if payload.event in (TriggerEvent.TASK_END, TriggerEvent.MESSAGE_THRESHOLD):
                self.extractor.on_trigger(payload)
            elif payload.event in (TriggerEvent.MEMORY_THRESHOLD, TriggerEvent.IMPORTANCE_SPIKE):
                self.reflector.on_trigger(payload)
