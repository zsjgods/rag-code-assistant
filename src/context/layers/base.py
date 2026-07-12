"""BaseLayer — abstract contract for all context layers.

Every layer provides:
  - render(): produce content for the final prompt
  - token_count(): estimate tokens consumed
  - clear(): reset to initial state
  - name: unique layer identifier
  - is_immutable: whether this layer survives compression
"""

from abc import ABC, abstractmethod
from src.context.types import LayerContent, LayerStats


class BaseLayer(ABC):
    """Abstract base class for all context layers.

    Subclasses must implement: name, render(), clear()
    Subclasses may set: is_immutable (default False)
    Subclasses may override: token_count()
    """

    # ── Class-level flags ──────────────────────────────

    is_immutable: bool = False
    """If True, this layer is never compressed, truncated, or summarized."""

    # ── Abstract interface ─────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique layer identifier (e.g. 'instruction', 'conversation')."""
        ...

    @abstractmethod
    def render(self) -> LayerContent:
        """Produce this layer's content for the final prompt.

        Returns:
            str  — for instruction-type layers (joined into system prompt)
            list[dict] — for message-type layers (extended into messages list)
        """
        ...

    @abstractmethod
    def clear(self) -> None:
        """Reset this layer to its initial state."""
        ...

    # ── Token estimation (default: char-based heuristic) ─

    def token_count(self) -> int:
        """Estimate tokens consumed by this layer.

        Uses the same 4-chars-per-token heuristic as src.compression.micro.
        Subclasses may override with model-specific tokenizers.
        """
        content = self.render()
        import json

        if isinstance(content, list):
            return len(json.dumps(content, default=str)) // 4
        return len(content) // 4

    # ── Budget info ────────────────────────────────────

    def get_budget_info(self, total_budget: int) -> LayerStats:
        """Return budget consumption statistics for this layer."""
        tokens = self.token_count()
        return LayerStats(
            layer_name=self.name,
            token_count=tokens,
            budget_used=tokens / total_budget if total_budget > 0 else 0.0,
            is_over_budget=False,  # set by PromptBuilder
        )
