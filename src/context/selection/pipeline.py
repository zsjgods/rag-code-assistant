"""SelectionPipeline — schedules Collect → Rank → Select → Pack.

Pure scheduler — never creates its own objects, never knows about Layers.
All components are injected at construction time.

The Pipeline is the ONLY entry point for context selection.
It returns SelectionResult — the unified output of the Context Engine.
"""

import time

from src.context.selection.candidate import Candidate
from src.context.selection.collector import Collector, SelectionContext
from src.context.selection.ranker import Ranker
from src.context.selection.policy import SelectionPolicy
from src.context.selection.packer import Packer, PromptPackage, SelectionResult, SelectionStats


class SelectionPipeline:
    """Schedules the context selection workflow.

    Usage:
        pipeline = SelectionPipeline(
            collectors=[InstructionCollector(), ConversationCollector(), ...],
            rankers=[PriorityRanker()],
            policy=BudgetSelectionPolicy([...]),
            packer=Packer(),
        )
        result = pipeline.run(ctx)
    """

    def __init__(
        self,
        collectors: list[Collector],
        rankers: list[Ranker],
        policy: SelectionPolicy,
        packer: Packer | None = None,
    ):
        # Index collectors by source_name for O(1) resolve lookup
        self._collectors: dict[str, Collector] = {
            c.source_name: c for c in collectors
        }
        self._rankers = rankers
        self._policy = policy
        self._packer = packer or Packer()

    @property
    def collectors(self) -> dict[str, Collector]:
        return dict(self._collectors)

    @property
    def rankers(self) -> list[Ranker]:
        return list(self._rankers)

    @property
    def policy(self) -> SelectionPolicy:
        return self._policy

    def run(self, ctx: SelectionContext) -> SelectionResult:
        """Execute the full selection pipeline.

        Phases:
          1. Collect — each Collector scans layers for Candidate references
          2. Rank — sort by priority + recency
          3. Select — apply policy constraints (budget)
          4. Pack — resolve references into PromptPackage
        """
        stats = SelectionStats()
        t_start = time.perf_counter()

        # ── Phase 1: Collect ────────────────────────────
        t0 = time.perf_counter()
        all_candidates: list[Candidate] = []
        for collector in self._collectors.values():
            all_candidates.extend(collector.collect(ctx))
        stats.collect_time_ms = (time.perf_counter() - t0) * 1000
        stats.total_candidates = len(all_candidates)
        stats.tokens_before = sum(c.token_count for c in all_candidates)

        # ── Phase 2: Rank ───────────────────────────────
        t0 = time.perf_counter()
        ranked = all_candidates
        for ranker in self._rankers:
            ranked = ranker.rank(ranked)
        stats.rank_time_ms = (time.perf_counter() - t0) * 1000

        # ── Phase 3: Select ─────────────────────────────
        t0 = time.perf_counter()
        selected, discarded = self._policy.select(ranked)
        stats.policy_time_ms = (time.perf_counter() - t0) * 1000
        stats.selected_candidates = len(selected)
        stats.discarded_candidates = len(discarded)
        stats.tokens_after = sum(c.token_count for c in selected)

        # ── Phase 4: Pack ───────────────────────────────
        t0 = time.perf_counter()
        package = self._packer.pack(selected, self._collectors, ctx)
        stats.pack_time_ms = (time.perf_counter() - t0) * 1000

        stats.total_time_ms = (time.perf_counter() - t_start) * 1000

        return SelectionResult(
            package=package,
            selected=selected,
            discarded=discarded,
            stats=stats,
        )
