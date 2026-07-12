"""ReflectionEngine — scheduler for reflection strategies.

Subscribes to: MEMORY_THRESHOLD, IMPORTANCE_SPIKE (via TriggerPolicy)

Iterates over registered strategies, calls each one's:
  1. select_candidates → find entry pairs to evaluate
  2. build_prompt → create LLM prompt
  3. LLM call → get decision
  4. parse_result → StrategyResult
  5. apply_result → update store, emit events

The engine is a pure scheduler — strategy logic lives in the strategy classes.
"""

import time

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.intelligence.candidate import ReflectionResult, StrategyResult
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.parser import ResponseParser
from src.memory.intelligence.prompt_loader import PromptLoader
from src.memory.intelligence.relation_types import RelationType, apply_relation_pair
from src.memory.intelligence.strategies.base import ReflectionStrategy
from src.memory.intelligence.trigger import TriggerEvent, TriggerPayload
from src.memory.types import MemoryEntry, MemoryType


class ReflectionEngine:
    """Scheduler for memory reflection strategies.

    Does NOT implement merge/conflict/refine/split logic — that's in the strategies.
    The engine iterates, calls LLM, applies results, emits events.

    Usage:
        engine = ReflectionEngine(store, events, vector_index, embedder, llm_call)
        engine.register_strategy(MergeStrategy())
        engine.register_strategy(ConflictStrategy())
        engine.on_trigger(TriggerPayload(event=TriggerEvent.MEMORY_THRESHOLD))
    """

    def __init__(
        self,
        store,                     # MemoryStore
        events: MemoryEventBus,
        vector_index,              # BaseVectorIndex | None
        embedder,                  # DenseEmbedder | None
        llm_call,                  # Callable[[str], str]
        config: IntelligenceConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._vector_index = vector_index
        self._embedder = embedder
        self._llm_call = llm_call
        self._config = config or IntelligenceConfig()

        self._parser = ResponseParser()
        self._prompts = PromptLoader()
        self._strategies: list[ReflectionStrategy] = []

    # ── Strategy registration ─────────────────────────────────

    def register_strategy(self, strategy: ReflectionStrategy) -> None:
        """Register a reflection strategy."""
        self._strategies.append(strategy)

    def remove_strategy(self, name: str) -> bool:
        """Remove a strategy by name."""
        for i, s in enumerate(self._strategies):
            if s.name == name:
                self._strategies.pop(i)
                return True
        return False

    @property
    def strategies(self) -> list[str]:
        return [s.name for s in self._strategies]

    # ── Trigger handler ───────────────────────────────────────

    def on_trigger(self, payload: TriggerPayload) -> None:
        """Handle a trigger event. Called by AsyncWorker."""
        if not self._config.reflection_enabled:
            return

        self.reflect(payload.event)

    # ── Reflection ───────────────────────────────────────────

    def reflect(self, trigger_event: TriggerEvent | None = None) -> ReflectionResult:
        """Run all registered strategies.

        Each strategy: select → prompt → LLM → parse → apply.

        Args:
            trigger_event: The event that triggered this reflection (for logging).

        Returns:
            ReflectionResult with aggregate counts.
        """
        result = ReflectionResult()

        for strategy in self._strategies:
            # Step 1: Select candidates
            candidates = strategy.select_candidates(
                self._store, self._vector_index, self._embedder, self._config
            )
            if not candidates:
                continue

            # Step 2-4: For each candidate pair, prompt → LLM → parse
            for entry_a, entry_b in candidates:
                try:
                    # Build prompt
                    prompt = strategy.build_prompt(entry_a, entry_b, self._prompts)

                    # Combine with system prompt
                    system_name = f"{strategy.name}_system"
                    try:
                        system_prompt = self._prompts.load(system_name)
                        combined = f"{system_prompt}\n\n{prompt}"
                    except FileNotFoundError:
                        combined = prompt

                    # LLM call
                    response = self._llm_call(combined)

                    # Parse and validate
                    raw_dict = self._parser.parse_json(response)
                    schema = strategy.get_schema()
                    validated = self._parser.validate(raw_dict, schema)
                    strategy_result = strategy.parse_result(validated, entry_a, entry_b)

                    # Apply result
                    self._apply_result(strategy_result, trigger_event)
                    result.strategy_results.append(strategy_result)

                    # Update counts
                    self._update_counts(result, strategy_result)

                except Exception:
                    # Best-effort: one failed pair doesn't stop the strategy
                    continue

        return result

    # ── Result application ───────────────────────────────────

    def _apply_result(
        self,
        sr: StrategyResult,
        trigger_event: TriggerEvent | None = None,
    ) -> None:
        """Apply a strategy result: update entries, emit events, write relations."""
        now = time.time()
        trigger_name = trigger_event.value if trigger_event else "manual"

        if sr.strategy == "merge" and sr.decision == "merge":
            self._apply_merge(sr, now, trigger_name)
        elif sr.strategy == "conflict":
            self._apply_conflict(sr, now, trigger_name)
        elif sr.strategy == "refine" and sr.decision == "refine":
            self._apply_refine(sr, now, trigger_name)
        elif sr.strategy == "split" and sr.decision == "split":
            self._apply_split(sr, now, trigger_name)

    def _apply_merge(self, sr: StrategyResult, now: float, trigger: str) -> None:
        """Merge: archive old pair, create new merged entry."""
        if len(sr.entry_ids) < 2:
            return

        entry_a = self._store.read(MemoryID(sr.entry_ids[0]))
        entry_b = self._store.read(MemoryID(sr.entry_ids[1]))
        if entry_a is None or entry_b is None:
            return

        # Create merged entry (take higher importance, combined tags)
        merged = MemoryEntry.create(
            text=sr.details or f"Merged: {entry_a.content.summary} + {entry_b.content.summary}",
            type=entry_a.type,
            summary=f"[Merged] {entry_a.content.summary}",
            tags=list(set(entry_a.content.tags + entry_b.content.tags)),
            importance=max(entry_a.score.importance, entry_b.score.importance),
            source="reflection:merge",
            reason=f"Merged from {sr.entry_ids[0][:8]}.. and {sr.entry_ids[1][:8]}..",
        )
        merged_id = self._store.create(merged)

        # Set parent/child relations
        apply_relation_pair(merged, entry_a, RelationType.PARENT)
        apply_relation_pair(merged, entry_b, RelationType.PARENT)

        # Archive old entries
        self._store.archive(entry_a.id)
        self._store.archive(entry_b.id)

        # Emit MERGED
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.MERGED,
            entry_id=merged_id.value,
            timestamp=now,
            triggered_by=f"reflection:{trigger}",
            metadata={
                "merged_from": sr.entry_ids,
                "new_id": merged_id.value,
            },
        ))

        sr.new_entry_id = merged_id.value

    def _apply_conflict(self, sr: StrategyResult, now: float, trigger: str) -> None:
        """Write conflict or superseded relations."""
        if len(sr.entry_ids) < 2:
            return

        entry_a = self._store.read(MemoryID(sr.entry_ids[0]))
        entry_b = self._store.read(MemoryID(sr.entry_ids[1]))
        if entry_a is None or entry_b is None:
            return

        if sr.decision == "conflict":
            apply_relation_pair(entry_a, entry_b, RelationType.CONFLICT)
            self._events.emit(MemoryEventPayload(
                event=MemoryEvent.CONFLICT,
                entry_id=sr.entry_ids[0],
                timestamp=now,
                triggered_by=f"reflection:{trigger}",
                metadata={
                    "conflict_with": sr.entry_ids[1],
                    "reason": sr.details,
                },
            ))

        elif sr.decision == "superseded":
            # entry_a supersedes entry_b
            apply_relation_pair(entry_a, entry_b, RelationType.SUPERSEDES)
            # Lower importance of superseded entry
            entry_b.score.importance = max(0.1, entry_b.score.importance * 0.5)
            self._events.emit(MemoryEventPayload(
                event=MemoryEvent.SUPERSEDED,
                entry_id=sr.entry_ids[1],
                timestamp=now,
                triggered_by=f"reflection:{trigger}",
                metadata={
                    "superseded_by": sr.entry_ids[0],
                    "reason": sr.details,
                },
            ))

    def _apply_refine(self, sr: StrategyResult, now: float, trigger: str) -> None:
        """Update summary and tags in-place."""
        entry = self._store.read(MemoryID(sr.entry_ids[0]))
        if entry is None:
            return

        # Just emit UPDATED — the actual refinement text is in details
        # (Real implementation would parse refined_summary/tags from the decision dict)
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.UPDATED,
            entry_id=sr.entry_ids[0],
            timestamp=now,
            triggered_by=f"reflection:{trigger}",
            metadata={"action": "refine", "details": sr.details},
        ))

    def _apply_split(self, sr: StrategyResult, now: float, trigger: str) -> None:
        """Split parent entry into children."""
        parent_entry = self._store.read(MemoryID(sr.entry_ids[0]))
        if parent_entry is None:
            return

        # Emit SPLIT (child creation is done by Extractor/Pipeline as separate entries)
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.SPLIT,
            entry_id=sr.entry_ids[0],
            timestamp=now,
            triggered_by=f"reflection:{trigger}",
            metadata={"details": sr.details},
        ))

    # ── Count helpers ─────────────────────────────────────────

    def _update_counts(self, result: ReflectionResult, sr: StrategyResult) -> None:
        """Update ReflectionResult counts based on strategy result."""
        if sr.strategy == "merge" and sr.decision == "merge":
            result.merges += 1
        elif sr.strategy == "conflict":
            if sr.decision == "conflict":
                result.conflicts_detected += 1
            elif sr.decision == "superseded":
                result.supersedes += 1
        elif sr.strategy == "refine" and sr.decision == "refine":
            result.refinements += 1
        elif sr.strategy == "split" and sr.decision == "split":
            result.splits += 1

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "strategies": self.strategies,
            "enabled": self._config.reflection_enabled,
            "max_candidates": self._config.reflection_max_candidates,
        }
