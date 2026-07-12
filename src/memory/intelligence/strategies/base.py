"""ReflectionStrategy — abstract base class for all reflection strategies.

Each strategy has 4 steps:
  1. select_candidates — pick entries from store using vector_index for coarse filter
  2. build_prompt       — create LLM prompt using PromptLoader
  3. parse_result       — convert LLM output + validated dict → StrategyResult
  4. get_schema         — return the JSON schema for validation

LLM call orchestration is handled by ReflectionEngine — strategies only
define what to select, how to prompt, and how to parse.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class ReflectionStrategy(ABC):
    """Abstract base for a reflection strategy.

    Each strategy is independent: its own file, own prompts, own logic.
    ReflectionEngine just iterates and calls these methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy name: 'merge', 'conflict', 'refine', 'split'."""
        ...

    @abstractmethod
    def select_candidates(
        self,
        store,                    # MemoryStore
        vector_index,             # BaseVectorIndex | None
        embedder,                 # DenseEmbedder | None
        config,                   # IntelligenceConfig
    ) -> list[tuple]:
        """Select candidate entry pairs for this strategy.

        Uses vector_index.search() for coarse semantic filtering.
        Returns list of (entry_a, entry_b_or_None) tuples.
        """
        ...

    @abstractmethod
    def build_prompt(
        self,
        entry_a,                  # MemoryEntry
        entry_b,                  # MemoryEntry | None
        prompt_loader,            # PromptLoader
    ) -> str:
        """Build the LLM prompt for this candidate pair.

        Uses PromptLoader to load .md templates with variable substitution.
        Returns the complete prompt string (user message content).
        """
        ...

    @abstractmethod
    def parse_result(
        self,
        decision: dict,           # Validated dict from LLM
        entry_a,                  # MemoryEntry
        entry_b,                  # MemoryEntry | None
    ) -> "StrategyResult":
        """Parse LLM decision into a StrategyResult.

        Args:
            decision: Validated dict with strategy-specific fields.
            entry_a: First entry in the pair.
            entry_b: Second entry (or None for single-entry strategies).

        Returns:
            StrategyResult with strategy name, decision, and affected entry IDs.
        """
        ...

    def get_schema(self) -> dict:
        """Return the JSON schema for LLM output validation.

        Override in subclasses for strategy-specific fields.
        Default schema works for simple decision outputs.
        """
        return {
            "required": ["decision", "reason"],
            "properties": {
                "decision": {"type": "str"},
                "reason": {"type": "str", "max": 500},
            },
        }
