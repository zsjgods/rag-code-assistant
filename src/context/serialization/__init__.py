"""Serialization — to_dict / from_dict for all Context Engine data types.

The serialization module is the foundation of M5 infrastructure:
  - RecoveryEngine uses it to persist/restore state via Store
  - AuditLog uses it to record every pipeline run
  - Replay uses it to rebuild historical prompts

Usage:
    from src.context.serialization import serialize, deserialize

    # Any supported type → dict
    data = serialize(selection_result)

    # dict → original type
    result = deserialize(data)

Architecture:
    schema.py     — Schema constants (_schema, _type markers, envelope helpers)
    serializer.py — to_dict / from_dict for each type + dispatch registry

All serialized payloads carry:
    _schema: version string (e.g. "1.0") — for future migration
    _type:   type marker (e.g. "SelectionResult") — for dispatch
"""

from src.context.serialization.schema import (
    SCHEMA_VERSION,
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
    make_envelope,
    has_envelope,
)
from src.context.serialization.serializer import (
    serialize,
    deserialize,
    register_type,
    # Individual to_dict (for callers that want type-specific serialization)
    candidate_to_dict,
    selection_stats_to_dict,
    prompt_package_to_dict,
    selection_result_to_dict,
    budget_report_to_dict,
    stage_result_to_dict,
    pipeline_result_to_dict,
    compression_plan_to_dict,
    summary_entry_to_dict,
    token_constraint_to_dict,
    # Individual from_dict (for callers that want type-specific deserialization)
    candidate_from_dict,
    selection_stats_from_dict,
    prompt_package_from_dict,
    selection_result_from_dict,
    budget_report_from_dict,
    stage_result_from_dict,
    pipeline_result_from_dict,
    compression_plan_from_dict,
    summary_entry_from_dict,
    token_constraint_from_dict,
)

__all__ = [
    # Schema
    "SCHEMA_VERSION",
    "TYPE_CANDIDATE",
    "TYPE_SELECTION_STATS",
    "TYPE_PROMPT_PACKAGE",
    "TYPE_SELECTION_RESULT",
    "TYPE_BUDGET_REPORT",
    "TYPE_STAGE_RESULT",
    "TYPE_PIPELINE_RESULT",
    "TYPE_COMPRESSION_PLAN",
    "TYPE_SUMMARY_ENTRY",
    "TYPE_TOKEN_CONSTRAINT",
    "make_envelope",
    "has_envelope",
    # Generic dispatch
    "serialize",
    "deserialize",
    "register_type",
    # Individual to_dict
    "candidate_to_dict",
    "selection_stats_to_dict",
    "prompt_package_to_dict",
    "selection_result_to_dict",
    "budget_report_to_dict",
    "stage_result_to_dict",
    "pipeline_result_to_dict",
    "compression_plan_to_dict",
    "summary_entry_to_dict",
    "token_constraint_to_dict",
    # Individual from_dict
    "candidate_from_dict",
    "selection_stats_from_dict",
    "prompt_package_from_dict",
    "selection_result_from_dict",
    "budget_report_from_dict",
    "stage_result_from_dict",
    "pipeline_result_from_dict",
    "compression_plan_from_dict",
    "summary_entry_from_dict",
    "token_constraint_from_dict",
]
