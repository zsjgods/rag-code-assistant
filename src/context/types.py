"""Shared types for the Context Engine.

Leaf module — no internal dependencies. Imported by all other context modules.
"""

from dataclasses import dataclass, field
from typing import Union

# A layer can render to either a system prompt string or a messages list
LayerContent = Union[str, list[dict]]


@dataclass
class BudgetConfig:
    """Token budget configuration for context layers.

    Each layer gets a fraction of the total context window.
    Ratios should sum to <= 1.0.
    """

    total_budget: int = 180000  # Total token budget for context window

    # M1 ratios (only 2 layers):
    instruction_ratio: float = 0.10  # 10% → immutable instruction
    conversation_ratio: float = 0.90  # 90% → conversation messages

    def budget_for(self, ratio: float) -> int:
        return int(self.total_budget * ratio)


@dataclass
class LayerStats:
    """Per-layer token usage statistics for observability."""

    layer_name: str
    token_count: int = 0
    budget_used: float = 0.0  # fraction of total budget (0.0 - 1.0)
    is_over_budget: bool = False


@dataclass
class BuildResult:
    """Result of a prompt build operation — the single exit point.

    system:  assembled system prompt string
    messages: conversation messages for the API call
    stats:   per-layer token breakdown (for observability)
    """

    system: str = ""
    messages: list = field(default_factory=list)
    stats: list = field(default_factory=list)  # list[LayerStats]
