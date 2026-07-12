"""DashboardBuilder — aggregates Context Engine runtime metrics.

Input:  SelectionResult + BudgetReport list + PipelineResult
Output: DashboardSnapshot

DashboardBuilder is pure aggregation — it has no state, no side effects,
and no knowledge of layers or pipeline internals.

Usage:
    snapshot = DashboardBuilder.build(
        selection_result=result,
        budget_reports=reports,
        pipeline_result=pipeline_result,
    )
    print(snapshot.summary_line())
    print(snapshot.to_dict())
"""

import time as time_module
from typing import Any

from src.context.selection.packer import SelectionResult, SelectionStats
from src.context.budget.manager import BudgetReport
from src.context.compression.pipeline import PipelineResult, StageResult

from src.context.observability.snapshot import (
    DashboardSnapshot,
    TokenBreakdown,
    SelectionBreakdown,
    SelectionSourceBreakdown,
    CompressionBreakdown,
    StageBreakdown,
    LatencyBreakdown,
)


class DashboardBuilder:
    """Aggregates runtime metrics into a DashboardSnapshot.

    All methods are static/class-level. No instance state.
    """

    @classmethod
    def build(
        cls,
        *,
        selection_result: SelectionResult | None = None,
        budget_reports: list[BudgetReport] | None = None,
        pipeline_result: PipelineResult | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DashboardSnapshot:
        """Aggregate all available metrics into a single snapshot.

        Every parameter is optional — missing data is simply omitted
        from the snapshot. This makes it safe to call from any code path
        (M4 path with SelectionResult, M3 path without, etc.).

        Args:
            selection_result: Output of SelectionPipeline.run().
            budget_reports: Output of BudgetManager.check().
            pipeline_result: Output of CompressionPipeline.execute().
            metadata: Additional metadata to attach to the snapshot.

        Returns:
            A DashboardSnapshot with all available metrics.
        """
        now = time_module.time()

        tokens = cls._build_tokens(selection_result, budget_reports)
        selection = cls._build_selection(selection_result)
        compression = cls._build_compression(pipeline_result)
        latency = cls._build_latency(selection_result, pipeline_result)

        return DashboardSnapshot(
            tokens=tokens,
            selection=selection,
            compression=compression,
            latency=latency,
            timestamp=now,
            metadata=metadata or {},
        )

    # ── Token aggregation ────────────────────────────────

    @classmethod
    def _build_tokens(
        cls,
        selection_result: SelectionResult | None,
        budget_reports: list[BudgetReport] | None,
    ) -> TokenBreakdown:
        """Build token breakdown from available sources.

        Priority: SelectionResult.token_usage (richer) → BudgetReports (fallback).
        """
        per_layer: dict[str, int] = {}

        # Best: from SelectionResult's resolved token usage
        if selection_result is not None:
            per_layer = dict(selection_result.package.token_usage)

        # Fallback: from BudgetReports (pre-selection, estimated)
        if not per_layer and budget_reports:
            for r in budget_reports:
                per_layer[r.layer_name] = r.token_count

        total = sum(per_layer.values())

        return TokenBreakdown(
            system=per_layer.get("instruction", 0)
            + per_layer.get("workspace", 0)
            + per_layer.get("file_cache", 0),
            conversation=per_layer.get("conversation", 0),
            summary=per_layer.get("summary", 0),
            workspace=per_layer.get("workspace", 0),
            file_cache=per_layer.get("file_cache", 0),
            total=total,
            per_layer=per_layer,
        )

    # ── Selection aggregation ────────────────────────────

    @classmethod
    def _build_selection(
        cls,
        selection_result: SelectionResult | None,
    ) -> SelectionBreakdown:
        """Build selection breakdown from SelectionResult."""
        if selection_result is None:
            return SelectionBreakdown()

        stats = selection_result.stats

        # Per-source breakdown
        by_source: dict[str, SelectionSourceBreakdown] = {}
        all_candidates = selection_result.selected + selection_result.discarded

        for c in all_candidates:
            src = c.layer_name
            if src not in by_source:
                by_source[src] = SelectionSourceBreakdown(source=src)
            by_source[src].candidates += 1
            by_source[src].tokens += c.token_count

        for c in selection_result.selected:
            by_source[c.layer_name].selected += 1

        for c in selection_result.discarded:
            by_source[c.layer_name].discarded += 1

        return SelectionBreakdown(
            total_candidates=max(
                stats.total_candidates,
                stats.selected_candidates + stats.discarded_candidates,
                len(all_candidates),
            ),
            selected=stats.selected_candidates or len(selection_result.selected),
            discarded=stats.discarded_candidates or len(selection_result.discarded),
            by_source=by_source,
        )

    # ── Compression aggregation ──────────────────────────

    @classmethod
    def _build_compression(
        cls,
        pipeline_result: PipelineResult | None,
    ) -> CompressionBreakdown | None:
        """Build compression breakdown from PipelineResult."""
        if pipeline_result is None:
            return None

        saved = pipeline_result.total_tokens_before - pipeline_result.total_tokens_after
        percent = (
            saved / pipeline_result.total_tokens_before
            if pipeline_result.total_tokens_before > 0
            else 0.0
        )

        stages = [
            StageBreakdown(
                stage_name=s.stage_name,
                tier=s.tier,
                skipped=s.skipped,
                tokens_before=s.tokens_before,
                tokens_after=s.tokens_after,
                saved_tokens=max(0, s.tokens_before - s.tokens_after),
                duration_ms=s.duration_ms,
                summary_updated=s.summary_updated,
                error=s.error,
            )
            for s in pipeline_result.stages
        ]

        return CompressionBreakdown(
            original_tokens=pipeline_result.total_tokens_before,
            compressed_tokens=pipeline_result.total_tokens_after,
            saved_tokens=max(0, saved),
            saved_percent=percent,
            stages=stages,
            active=pipeline_result.action == "compress",
        )

    # ── Latency aggregation ──────────────────────────────

    @classmethod
    def _build_latency(
        cls,
        selection_result: SelectionResult | None,
        pipeline_result: PipelineResult | None,
    ) -> LatencyBreakdown:
        """Build latency breakdown from available sources."""
        latency = LatencyBreakdown()

        if selection_result is not None:
            stats = selection_result.stats
            latency.collect_ms = stats.collect_time_ms
            latency.rank_ms = stats.rank_time_ms
            latency.select_ms = stats.policy_time_ms
            latency.pack_ms = stats.pack_time_ms
            latency.total_ms += stats.total_time_ms

        if pipeline_result is not None:
            # Sum of non-skipped stage durations
            for stage in pipeline_result.stages:
                if not stage.skipped:
                    latency.compression_ms += stage.duration_ms
            latency.total_ms += latency.compression_ms

        return latency

    # ── Convenience for inline use ───────────────────────

    @classmethod
    def quick(
        cls,
        selection_result: SelectionResult | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DashboardSnapshot:
        """Quick one-call snapshot from just a SelectionResult.

        Shorthand for builds() with only selection data available.
        """
        return cls.build(
            selection_result=selection_result,
            metadata=metadata,
        )
