"""Serializer — to_dict / from_dict for all Context Engine data types.

Every serializable type has two functions:
  - to_dict(obj) -> dict       (with _schema + _type envelope)
  - from_dict(data) -> object  (validates envelope before dispatch)

Module-level serialize() / deserialize() dispatch to the correct handler
based on the _type marker, so callers (Recovery, Audit, Replay) never
need to import individual type functions.

Types supported (see schema.TYPE_* constants):
  Candidate, SelectionStats, PromptPackage, SelectionResult,
  BudgetReport, StageResult, PipelineResult, CompressionPlan,
  SummaryEntry, TokenConstraint
"""

from typing import Any

from src.context.selection.candidate import Candidate
from src.context.selection.packer import PromptPackage, SelectionResult, SelectionStats
from src.context.selection.policy import TokenConstraint
from src.context.budget.manager import BudgetReport
from src.context.compression.pipeline import StageResult, PipelineResult
from src.context.compression.policy import CompressionPlan
from src.context.layers.summary import SummaryEntry

from src.context.serialization.schema import (
    TYPE_CANDIDATE,
    TYPE_SELECTION_STATS,
    TYPE_PROMPT_PACKAGE,
    TYPE_SELECTION_RESULT,
    TYPE_BUDGET_REPORT,
    TYPE_STAGE_RESULT,
    TYPE_PIPELINE_RESULT,
    TYPE_COMPRESSION_PLAN,
    TYPE_SUMMARY_ENTRY,
    TYPE_TOKEN_CONSTRAINT,
    KEY_TYPE,
    make_envelope,
    has_envelope,
)


# ═══════════════════════════════════════════════════════════════════════
#  to_dict implementations
# ═══════════════════════════════════════════════════════════════════════

def candidate_to_dict(obj: Candidate) -> dict:
    """Serialize a Candidate to a plain dict."""
    return {
        **make_envelope(TYPE_CANDIDATE),
        "layer_name": obj.layer_name,
        "item_id": obj.item_id,
        "recency": obj.recency,
        "token_count": obj.token_count,
        "importance": obj.importance,
        "metadata": dict(obj.metadata),
    }


def selection_stats_to_dict(obj: SelectionStats) -> dict:
    """Serialize SelectionStats to a plain dict."""
    return {
        **make_envelope(TYPE_SELECTION_STATS),
        "total_candidates": obj.total_candidates,
        "selected_candidates": obj.selected_candidates,
        "discarded_candidates": obj.discarded_candidates,
        "collect_time_ms": obj.collect_time_ms,
        "rank_time_ms": obj.rank_time_ms,
        "policy_time_ms": obj.policy_time_ms,
        "pack_time_ms": obj.pack_time_ms,
        "total_time_ms": obj.total_time_ms,
        "tokens_before": obj.tokens_before,
        "tokens_after": obj.tokens_after,
    }


def prompt_package_to_dict(obj: PromptPackage) -> dict:
    """Serialize a PromptPackage to a plain dict."""
    return {
        **make_envelope(TYPE_PROMPT_PACKAGE),
        "system_parts": list(obj.system_parts),
        "message_parts": list(obj.message_parts),
        "token_usage": dict(obj.token_usage),
        "total_tokens": obj.total_tokens,
    }


def selection_result_to_dict(obj: SelectionResult) -> dict:
    """Serialize a SelectionResult to a plain dict."""
    return {
        **make_envelope(TYPE_SELECTION_RESULT),
        "package": prompt_package_to_dict(obj.package),
        "selected": [candidate_to_dict(c) for c in obj.selected],
        "discarded": [candidate_to_dict(c) for c in obj.discarded],
        "stats": selection_stats_to_dict(obj.stats),
    }


def budget_report_to_dict(obj: BudgetReport) -> dict:
    """Serialize a BudgetReport to a plain dict."""
    return {
        **make_envelope(TYPE_BUDGET_REPORT),
        "budget_name": obj.budget_name,
        "layer_name": obj.layer_name,
        "token_count": obj.token_count,
        "budget_limit": obj.budget_limit,
        "over_budget": obj.over_budget,
        "excess": obj.excess,
    }


def stage_result_to_dict(obj: StageResult) -> dict:
    """Serialize a StageResult to a plain dict."""
    return {
        **make_envelope(TYPE_STAGE_RESULT),
        "stage_name": obj.stage_name,
        "tier": obj.tier,
        "skipped": obj.skipped,
        "tokens_before": obj.tokens_before,
        "tokens_after": obj.tokens_after,
        "messages_before": obj.messages_before,
        "messages_after": obj.messages_after,
        "summary_updated": obj.summary_updated,
        "duration_ms": obj.duration_ms,
        "error": obj.error,
    }


def pipeline_result_to_dict(obj: PipelineResult) -> dict:
    """Serialize a PipelineResult to a plain dict."""
    return {
        **make_envelope(TYPE_PIPELINE_RESULT),
        "stages": [stage_result_to_dict(s) for s in obj.stages],
        "action": obj.action,
        "total_tokens_before": obj.total_tokens_before,
        "total_tokens_after": obj.total_tokens_after,
    }


def compression_plan_to_dict(obj: CompressionPlan) -> dict:
    """Serialize a CompressionPlan to a plain dict."""
    payload: dict = {
        **make_envelope(TYPE_COMPRESSION_PLAN),
        "action": obj.action,
        "layer_name": obj.layer_name,
        "target_tokens": obj.target_tokens,
        "max_tier": obj.max_tier,
    }
    if obj.triggered_by:
        payload["triggered_by"] = budget_report_to_dict(obj.triggered_by)
    return payload


def summary_entry_to_dict(obj: SummaryEntry) -> dict:
    """Serialize a SummaryEntry to a plain dict."""
    return {
        **make_envelope(TYPE_SUMMARY_ENTRY),
        "content": obj.content,
        "token_count": obj.token_count,
        "version": obj.version,
        "created_at": obj.created_at,
        "last_used_at": obj.last_used_at,
        "importance": obj.importance,
        "access_count": obj.access_count,
        "source": obj.source,
        "metadata": dict(obj.metadata),
    }


def token_constraint_to_dict(obj: TokenConstraint) -> dict:
    """Serialize a TokenConstraint to a plain dict."""
    return {
        **make_envelope(TYPE_TOKEN_CONSTRAINT),
        "source": obj.source,
        "max_tokens": obj.max_tokens,
        "reserved": obj.reserved,
    }


# ═══════════════════════════════════════════════════════════════════════
#  from_dict implementations
# ═══════════════════════════════════════════════════════════════════════

def candidate_from_dict(data: dict) -> Candidate:
    """Deserialize a Candidate from a dict."""
    return Candidate(
        layer_name=data["layer_name"],
        item_id=data["item_id"],
        recency=data.get("recency", 0.0),
        token_count=data.get("token_count", 0),
        importance=data.get("importance", 0.5),
        metadata=dict(data.get("metadata", {})),
    )


def selection_stats_from_dict(data: dict) -> SelectionStats:
    """Deserialize SelectionStats from a dict."""
    return SelectionStats(
        total_candidates=data.get("total_candidates", 0),
        selected_candidates=data.get("selected_candidates", 0),
        discarded_candidates=data.get("discarded_candidates", 0),
        collect_time_ms=data.get("collect_time_ms", 0.0),
        rank_time_ms=data.get("rank_time_ms", 0.0),
        policy_time_ms=data.get("policy_time_ms", 0.0),
        pack_time_ms=data.get("pack_time_ms", 0.0),
        total_time_ms=data.get("total_time_ms", 0.0),
        tokens_before=data.get("tokens_before", 0),
        tokens_after=data.get("tokens_after", 0),
    )


def prompt_package_from_dict(data: dict) -> PromptPackage:
    """Deserialize a PromptPackage from a dict."""
    return PromptPackage(
        system_parts=list(data.get("system_parts", [])),
        message_parts=list(data.get("message_parts", [])),
        token_usage=dict(data.get("token_usage", {})),
        total_tokens=data.get("total_tokens", 0),
    )


def selection_result_from_dict(data: dict) -> SelectionResult:
    """Deserialize a SelectionResult from a dict."""
    package_data = data.get("package", {})
    if has_envelope(package_data):
        package = prompt_package_from_dict(package_data)
    else:
        package = PromptPackage()

    return SelectionResult(
        package=package,
        selected=[candidate_from_dict(c) for c in data.get("selected", [])],
        discarded=[candidate_from_dict(c) for c in data.get("discarded", [])],
        stats=selection_stats_from_dict(data.get("stats", {})),
    )


def budget_report_from_dict(data: dict) -> BudgetReport:
    """Deserialize a BudgetReport from a dict."""
    return BudgetReport(
        budget_name=data.get("budget_name", "token"),
        layer_name=data.get("layer_name", ""),
        token_count=data.get("token_count", 0),
        budget_limit=data.get("budget_limit", 0),
        over_budget=data.get("over_budget", False),
        excess=data.get("excess", 0),
    )


def stage_result_from_dict(data: dict) -> StageResult:
    """Deserialize a StageResult from a dict."""
    return StageResult(
        stage_name=data.get("stage_name", ""),
        tier=data.get("tier", 0),
        skipped=data.get("skipped", False),
        tokens_before=data.get("tokens_before", 0),
        tokens_after=data.get("tokens_after", 0),
        messages_before=data.get("messages_before", 0),
        messages_after=data.get("messages_after", 0),
        summary_updated=data.get("summary_updated", False),
        duration_ms=data.get("duration_ms", 0.0),
        error=data.get("error"),
    )


def pipeline_result_from_dict(data: dict) -> PipelineResult:
    """Deserialize a PipelineResult from a dict."""
    stages_raw = data.get("stages", [])
    stages = [
        stage_result_from_dict(s) if isinstance(s, dict) else s
        for s in stages_raw
    ]
    return PipelineResult(
        stages=stages,
        action=data.get("action", "noop"),
        total_tokens_before=data.get("total_tokens_before", 0),
        total_tokens_after=data.get("total_tokens_after", 0),
    )


def compression_plan_from_dict(data: dict) -> CompressionPlan:
    """Deserialize a CompressionPlan from a dict."""
    triggered_by_data = data.get("triggered_by")
    triggered_by = (
        budget_report_from_dict(triggered_by_data)
        if isinstance(triggered_by_data, dict)
        else None
    )
    return CompressionPlan(
        action=data.get("action", "noop"),
        layer_name=data.get("layer_name", ""),
        target_tokens=data.get("target_tokens", 0),
        max_tier=data.get("max_tier", 3),
        triggered_by=triggered_by,
    )


def summary_entry_from_dict(data: dict) -> SummaryEntry:
    """Deserialize a SummaryEntry from a dict."""
    return SummaryEntry(
        content=data.get("content", ""),
        token_count=data.get("token_count", 0),
        version=data.get("version", 0),
        created_at=data.get("created_at", 0.0),
        last_used_at=data.get("last_used_at", 0.0),
        importance=data.get("importance", 1.0),
        access_count=data.get("access_count", 0),
        source=data.get("source", ""),
        metadata=dict(data.get("metadata", {})),
    )


def token_constraint_from_dict(data: dict) -> TokenConstraint:
    """Deserialize a TokenConstraint from a dict."""
    return TokenConstraint(
        source=data.get("source", ""),
        max_tokens=data.get("max_tokens", 0),
        reserved=data.get("reserved", False),
    )


# ═══════════════════════════════════════════════════════════════════════
#  Dispatch registry — maps _type markers to (to_dict, from_dict)
# ═══════════════════════════════════════════════════════════════════════

_REGISTRY: dict[str, tuple] = {
    TYPE_CANDIDATE: (candidate_to_dict, candidate_from_dict),
    TYPE_SELECTION_STATS: (selection_stats_to_dict, selection_stats_from_dict),
    TYPE_PROMPT_PACKAGE: (prompt_package_to_dict, prompt_package_from_dict),
    TYPE_SELECTION_RESULT: (selection_result_to_dict, selection_result_from_dict),
    TYPE_BUDGET_REPORT: (budget_report_to_dict, budget_report_from_dict),
    TYPE_STAGE_RESULT: (stage_result_to_dict, stage_result_from_dict),
    TYPE_PIPELINE_RESULT: (pipeline_result_to_dict, pipeline_result_from_dict),
    TYPE_COMPRESSION_PLAN: (compression_plan_to_dict, compression_plan_from_dict),
    TYPE_SUMMARY_ENTRY: (summary_entry_to_dict, summary_entry_from_dict),
    TYPE_TOKEN_CONSTRAINT: (token_constraint_to_dict, token_constraint_from_dict),
}


def register_type(
    type_name: str,
    to_dict_fn: callable,
    from_dict_fn: callable,
) -> None:
    """Register a custom serializable type.

    Allows external modules (e.g., future RAG) to add their own types
    without modifying the serializer.

    Args:
        type_name: A unique TYPE_* constant string.
        to_dict_fn: Callable(obj) -> dict (with envelope).
        from_dict_fn: Callable(data) -> object.
    """
    _REGISTRY[type_name] = (to_dict_fn, from_dict_fn)


# ═══════════════════════════════════════════════════════════════════════
#  Generic serialize / deserialize entry points
# ═══════════════════════════════════════════════════════════════════════


def serialize(obj: Any) -> dict:
    """Serialize any registered type to a dict.

    Automatically routes based on the object's type.

    Args:
        obj: A supported dataclass instance.

    Returns:
        A dict with _schema + _type envelope.

    Raises:
        ValueError: If the type is not registered.
    """
    # Map types to their _type markers (reverse lookup)
    type_name = _class_to_type(type(obj))
    if type_name is None:
        raise ValueError(
            f"Cannot serialize {type(obj).__name__}: "
            f"not a registered serializable type. "
            f"Registered: {list(_REGISTRY.keys())}"
        )
    to_dict_fn = _REGISTRY[type_name][0]
    return to_dict_fn(obj)


def deserialize(data: dict) -> Any:
    """Deserialize any registered type from a dict.

    Automatically routes based on the _type envelope field.

    Args:
        data: A dict with at least _schema and _type keys.

    Returns:
        An instance of the appropriate dataclass type.

    Raises:
        ValueError: If _type is missing, unknown, or data is not a dict.
    """
    if not isinstance(data, dict):
        raise ValueError(f"Cannot deserialize: expected dict, got {type(data).__name__}")
    type_name = data.get(KEY_TYPE)
    if not type_name:
        raise ValueError(
            f"Cannot deserialize: missing '{KEY_TYPE}' in data. "
            f"Keys: {list(data.keys())}"
        )
    from_dict_fn = _REGISTRY.get(type_name, (None, None))[1]
    if from_dict_fn is None:
        raise ValueError(
            f"Cannot deserialize: unknown type '{type_name}'. "
            f"Registered: {list(_REGISTRY.keys())}"
        )
    return from_dict_fn(data)


def _class_to_type(cls: type) -> str | None:
    """Reverse-lookup the _type marker for a Python class."""
    mapping = {
        Candidate: TYPE_CANDIDATE,
        SelectionStats: TYPE_SELECTION_STATS,
        PromptPackage: TYPE_PROMPT_PACKAGE,
        SelectionResult: TYPE_SELECTION_RESULT,
        BudgetReport: TYPE_BUDGET_REPORT,
        StageResult: TYPE_STAGE_RESULT,
        PipelineResult: TYPE_PIPELINE_RESULT,
        CompressionPlan: TYPE_COMPRESSION_PLAN,
        SummaryEntry: TYPE_SUMMARY_ENTRY,
        TokenConstraint: TYPE_TOKEN_CONSTRAINT,
    }
    return mapping.get(cls)
