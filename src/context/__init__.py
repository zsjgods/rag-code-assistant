"""Context Engine — Layered context management for the agent framework.

Architecture:
  ContextOrchestrator (single entry point)
    ├── PromptBuilder (single exit point)
    ├── M4 SelectionPipeline (Collect → Rank → Select → Pack)
    └── Layers (Instruction, Conversation, Workspace, FileCache, Summary)

Milestones:
  M1: Layer Registry + PromptBuilder + InstructionLayer + ConversationLayer
  M2: WorkspaceLayer + FileCacheLayer + Project Detector
  M3: SummaryLayer + BudgetManager + CompressionPolicy + CompressionPipeline
  M4: Context Selection Pipeline (Collector/Ranker/Policy/Packer) + PromptPackage

Architecture boundary (final):
  Layer         → stores data
  Collector     → produces Candidate references + resolves content
  Candidate     → immutable fact reference
  Ranker        → sorts via PriorityProvider
  Policy        → applies constraints (token budget)
  Packer        → resolves Candidates → PromptPackage
  PromptBuilder → renders PromptPackage into LLM format
"""

from src.context.orchestrator import ContextOrchestrator
from src.context.prompt_builder import PromptBuilder
from src.context.layers.base import BaseLayer
from src.context.layers.instruction import InstructionLayer
from src.context.layers.conversation import ConversationLayer
from src.context.layers.workspace import WorkspaceLayer
from src.context.layers.file_cache import FileCacheLayer
from src.context.layers.summary import SummaryLayer, SummaryEntry
from src.context.types import BuildResult, BudgetConfig, LayerStats, LayerContent

# M3: budget + compression
from src.context.budget import Budget, BudgetAllocation, BudgetPolicy, BudgetManager, BudgetReport
from src.context.compression import (
    CompressionRule, OverBudgetRule, CompressionPolicy, CompressionPlan,
    Summarizer, LLMSummarizer, SimpleSummarizer,
    CompressionPipeline, CompressionStage, CompressionContext,
    StageResult, PipelineResult,
    MicroCompactStage, ContextCollapseStage, AutoCompactStage,
)

# M5: Serialization infrastructure (to_dict / from_dict for all types)
from src.context.serialization import (
    SCHEMA_VERSION,
    make_envelope, has_envelope,
    serialize, deserialize, register_type,
    # Individual to_dict
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
    # Individual from_dict
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

# M5: Recovery — state persistence and restoration
from src.context.recovery import (
    RecoveryEngine,
    SummaryState,
    WorkspaceState,
    SessionState,
    MigrationRegistry,
    MigrationError,
)

# M5: Observability — Dashboard, Trace, Audit
from src.context.observability import (
    DashboardSnapshot,
    TokenBreakdown,
    SelectionBreakdown,
    SelectionSourceBreakdown,
    CompressionBreakdown,
    StageBreakdown,
    LatencyBreakdown,
    DashboardBuilder,
    ExecutionTrace,
    TraceEvent,
    AuditLog,
)

# M5: Replay — historical prompt reconstruction + diff
from src.context.replay import (
    ReplayEngine,
    SnapshotDiff,
    DiffReport,
)

# M4: Context Selection Pipeline
from src.context.selection import (
    Candidate, Collector, SelectionContext,
    InstructionCollector, WorkspaceCollector, SummaryCollector,
    FileCacheCollector, ConversationCollector,
    Ranker, PriorityProvider, PriorityRanker,
    SelectionPolicy, TokenConstraint, BudgetSelectionPolicy,
    Packer, PromptPackage, SelectionResult, SelectionStats,
    SelectionPipeline,
)

__all__ = [
    # Orchestrator
    "ContextOrchestrator",
    # Builder
    "PromptBuilder",
    # M1 Layers
    "BaseLayer",
    "InstructionLayer",
    "ConversationLayer",
    # M2 Layers
    "WorkspaceLayer",
    "FileCacheLayer",
    # M3 Layers
    "SummaryLayer",
    "SummaryEntry",
    # M3 Budget
    "Budget",
    "BudgetAllocation",
    "BudgetPolicy",
    "BudgetManager",
    "BudgetReport",
    # M3 Policy
    "CompressionRule",
    "OverBudgetRule",
    "CompressionPolicy",
    "CompressionPlan",
    # M3 Summarizer
    "Summarizer",
    "LLMSummarizer",
    "SimpleSummarizer",
    # M3 Pipeline
    "CompressionPipeline",
    "CompressionStage",
    "CompressionContext",
    "StageResult",
    "PipelineResult",
    "MicroCompactStage",
    "ContextCollapseStage",
    "AutoCompactStage",
    # M4 Context Selection
    "Candidate",
    "Collector",
    "SelectionContext",
    "InstructionCollector",
    "WorkspaceCollector",
    "SummaryCollector",
    "FileCacheCollector",
    "ConversationCollector",
    "Ranker",
    "PriorityProvider",
    "PriorityRanker",
    "SelectionPolicy",
    "TokenConstraint",
    "BudgetSelectionPolicy",
    "Packer",
    "PromptPackage",
    "SelectionResult",
    "SelectionStats",
    "SelectionPipeline",
    # M5 Serialization
    "SCHEMA_VERSION",
    "make_envelope", "has_envelope",
    "serialize", "deserialize", "register_type",
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
    # M5 Recovery
    "RecoveryEngine",
    "SummaryState",
    "WorkspaceState",
    "SessionState",
    "MigrationRegistry",
    "MigrationError",
    # M5 Observability
    "DashboardSnapshot",
    "TokenBreakdown",
    "SelectionBreakdown",
    "SelectionSourceBreakdown",
    "CompressionBreakdown",
    "StageBreakdown",
    "LatencyBreakdown",
    "DashboardBuilder",
    "ExecutionTrace",
    "TraceEvent",
    "AuditLog",
    # M5 Replay
    "ReplayEngine",
    "SnapshotDiff",
    "DiffReport",
    # Types
    "BuildResult",
    "BudgetConfig",
    "LayerStats",
    "LayerContent",
]
