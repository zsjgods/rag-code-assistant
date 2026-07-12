"""Schema constants and type definitions for Context Engine serialization.

This module defines:
  - SCHEMA_VERSION: The current schema version string.
  - SCHEMA_TYPES: Enum-like constants for each serializable type.
  - Type aliases for serialized dict representations.

Every serialized payload includes `_schema` and `_type` fields for
version-aware deserialization and migration (Phase 2).

Version history:
  1.0 — Initial M5 serialization format (Candidate, SelectionStats,
         PromptPackage, SelectionResult, BudgetReport, StageResult,
         PipelineResult, CompressionPlan, SummaryEntry)
"""

SCHEMA_VERSION = "1.0"

# ── Type markers (embedded in every serialized dict) ────────────────────

TYPE_CANDIDATE = "Candidate"
TYPE_SELECTION_STATS = "SelectionStats"
TYPE_PROMPT_PACKAGE = "PromptPackage"
TYPE_SELECTION_RESULT = "SelectionResult"
TYPE_BUDGET_REPORT = "BudgetReport"
TYPE_STAGE_RESULT = "StageResult"
TYPE_PIPELINE_RESULT = "PipelineResult"
TYPE_COMPRESSION_PLAN = "CompressionPlan"
TYPE_SUMMARY_ENTRY = "SummaryEntry"
TYPE_TOKEN_CONSTRAINT = "TokenConstraint"

# ── Standard envelope keys ──────────────────────────────────────────────

KEY_SCHEMA = "_schema"
KEY_TYPE = "_type"

# ── Serialized type aliases (for readability) ───────────────────────────

SerializedDict = dict  # A serialized data structure as a plain dict
CandidateData = dict
SelectionStatsData = dict
PromptPackageData = dict
SelectionResultData = dict
BudgetReportData = dict
StageResultData = dict
PipelineResultData = dict
SummaryEntryData = dict
CompressionPlanData = dict


def make_envelope(type_name: str, version: str | None = None) -> dict:
    """Create a schema envelope dict.

    Every serialized payload starts with _schema + _type so that
    deserializers can route to the correct handler.

    Args:
        type_name: One of the TYPE_* constants.
        version: Schema version string (defaults to SCHEMA_VERSION).

    Returns:
        Dict with _schema and _type keys.
    """
    return {
        KEY_SCHEMA: version or SCHEMA_VERSION,
        KEY_TYPE: type_name,
    }


def has_envelope(data: dict) -> bool:
    """Check whether a dict carries a schema envelope."""
    return KEY_SCHEMA in data and KEY_TYPE in data
