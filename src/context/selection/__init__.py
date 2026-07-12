"""Context Selection Pipeline — decides WHAT goes into the final prompt.

Architecture boundary (final):
  Layer         → stores data (get/list/render)
  Collector     → produces Candidate references + resolves content
  Candidate     → immutable fact reference (no priority, no content)
  Ranker        → sorts via PriorityProvider (priority external to Candidate)
  Policy        → applies constraints (token budget)
  Packer        → calls resolve(), assembles PromptPackage
  PromptBuilder → renders PromptPackage into LLM format
"""

from src.context.selection.candidate import Candidate
from src.context.selection.collector import Collector, SelectionContext
from src.context.selection.collectors import (
    InstructionCollector,
    WorkspaceCollector,
    SummaryCollector,
    FileCacheCollector,
    ConversationCollector,
)
from src.context.selection.ranker import Ranker, PriorityProvider, PriorityRanker
from src.context.selection.policy import SelectionPolicy, TokenConstraint, BudgetSelectionPolicy
from src.context.selection.packer import Packer, PromptPackage, SelectionResult, SelectionStats
from src.context.selection.pipeline import SelectionPipeline

__all__ = [
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
]

