"""Data models for M9 Intelligence Layer.

MemoryCandidate    — LLM extraction output (NOT a MemoryEntry)
StrategyResult     — Reflection strategy output (merge/conflict/refine/split)
ExtractionResult   — Summary of an extraction run
ReflectionResult   — Summary of a reflection run
"""

from dataclasses import dataclass, field
from enum import StrEnum

from src.memory.identity import MemoryID


class CandidateType(StrEnum):
    """Type of knowledge extracted by LLM."""
    FACT = "fact"              # Verifiable fact
    DECISION = "decision"      # A choice was made
    PREFERENCE = "preference"  # User preference/habit
    EXPERIENCE = "experience"  # Lesson learned or pitfall


@dataclass
class MemoryCandidate:
    """LLM-extracted memory candidate. NOT a MemoryEntry.

    LLM outputs this → Validator checks it → Pipeline creates MemoryEntry.
    LLM is the Proposer, NOT the Authority.

    estimated_importance is a suggestion only — M8 ImportanceEngine
    recomputes the real importance during Pipeline processing.
    """

    type: str = "knowledge"           # MemoryType value
    text: str = ""                    # Full content
    summary: str = ""                 # One-line summary
    tags: list[str] = field(default_factory=list)
    estimated_importance: float = 0.5  # LLM suggestion (reference only)
    confidence: float = 0.5           # LLM self-assessed confidence
    reason: str = ""                  # Why this is worth remembering
    source_quote: str = ""            # Verbatim quote from source (hallucination guard)
    source_message_index: int = -1    # Which message in the conversation
    candidate_type: str = "fact"      # CandidateType value


@dataclass
class StrategyResult:
    """Output of a single ReflectionStrategy execution.

    Contains the decision type and the entries affected.
    """

    strategy: str                     # "merge" | "conflict" | "refine" | "split"
    decision: str                     # Strategy-specific decision
    entry_ids: list[str] = field(default_factory=list)  # Affected entry IDs
    new_entry_id: str | None = None   # ID of newly created entry (if any)
    details: str = ""                 # Human-readable explanation


@dataclass
class ExtractionResult:
    """Summary of an extraction run."""

    candidates_generated: int = 0
    candidates_accepted: int = 0
    candidates_rejected: int = 0
    entries_created: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class ReflectionResult:
    """Summary of a reflection run."""

    strategy_results: list[StrategyResult] = field(default_factory=list)
    merges: int = 0
    conflicts_detected: int = 0
    refinements: int = 0
    splits: int = 0
    supersedes: int = 0

    @property
    def total_actions(self) -> int:
        return self.merges + self.conflicts_detected + self.refinements + self.splits + self.supersedes
