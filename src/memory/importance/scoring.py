"""ImportanceScorer — computes base importance from MemoryType and source.

type_weight × source_weight → importance ∈ [0, 1]

Also provides sigmoid-based access boost for diminishing returns on repeated access.
"""

import math

from src.memory.importance.config import ImportanceConfig
from src.memory.types import MemoryEntry, MemoryScore


class ImportanceScorer:
    """Compute and adjust importance scores.

    Usage:
        scorer = ImportanceScorer(config)
        base = scorer.compute_base(entry)           # type_weight × source_weight
        boosted = scorer.access_boost(score, 1)     # sigmoid boost per access
    """

    def __init__(self, config: ImportanceConfig | None = None):
        self._config = config or ImportanceConfig()

    # ═══════════════════════════════════════════════════════════
    # Base importance
    # ═══════════════════════════════════════════════════════════

    def compute_base(self, entry: MemoryEntry) -> float:
        """Compute importance baseline for an entry.

        importance = type_weight × source_weight, clamped to [0, 1].

        Args:
            entry: A MemoryEntry with identity.type and content.source set.

        Returns:
            Base importance score in [0, 1].
        """
        tw = self._config.type_weights.get(entry.type.value, 0.50)
        sw = self._config.source_weights.get(entry.content.source, 0.50)
        return max(0.0, min(1.0, tw * sw))

    def should_override(self, entry: MemoryEntry) -> bool:
        """Check whether the entry's importance should be auto-computed.

        Returns True if:
          - override_on_create is enabled, AND
          - (only_override_default is False OR importance is close to 0.5)
        """
        if not self._config.override_on_create:
            return False
        if self._config.only_override_default:
            # Check if importance is at the default (0.5 ± epsilon)
            return abs(entry.score.importance - 0.5) < 0.001
        return True

    # ═══════════════════════════════════════════════════════════
    # Access boost (diminishing returns)
    # ═══════════════════════════════════════════════════════════

    def access_boost(self, importance: float, n_accesses: int = 1) -> float:
        """Apply sigmoid-based boost for each access.

        boost = access_boost × sigmoid(k × (cap - current_importance))
        This ensures diminishing returns: frequently accessed memories
        don't inflate to 1.0, and low-importance memories get a larger
        per-access boost than high-importance ones.

        Args:
            importance: Current importance score.
            n_accesses: Number of new accesses (boost applied n times).

        Returns:
            New importance score (still in [0, 1]).
        """
        cfg = self._config
        for _ in range(n_accesses):
            gap = cfg.access_boost_cap - importance
            if gap <= 0:
                break
            # Sigmoid: closer to cap → smaller boost
            boost = cfg.access_boost * self._sigmoid(cfg.access_boost_k * gap)
            importance = min(cfg.access_boost_cap, importance + boost)
        return importance

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Sigmoid function, output in (0, 1)."""
        if x > 20:
            return 1.0
        if x < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))
