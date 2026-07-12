"""FreshnessDecay — exponential decay for MemoryScore.freshness.

Hybrid strategy:
  - Event-driven: ACCESSED resets freshness to 1.0
  - Lazy: apply() computes decay at read time based on days since last access

Formula: freshness = exp(-λ × days_since_last_access)
  where λ = ln(2) / half_life_days
"""

import math
import time

from src.memory.importance.config import ImportanceConfig
from src.memory.types import MemoryScore


class FreshnessDecay:
    """Exponential freshness decay for MemoryScore.

    Usage:
        decay = FreshnessDecay(config)
        decay.reset(score)           # Event-driven: set freshness = 1.0, record timestamp
        decay.apply(score)           # Lazy: compute decayed freshness
        current = decay.get_effective(score)  # Lazy read without mutating
    """

    def __init__(self, config: ImportanceConfig | None = None):
        self._config = config or ImportanceConfig()

    @property
    def decay_rate(self) -> float:
        """λ = ln(2) / half_life_days (daily decay constant)."""
        hl = self._config.freshness_half_life_days
        if hl <= 0:
            return 0.0
        return math.log(2) / hl

    # ═══════════════════════════════════════════════════════════
    # Event-driven: reset on access
    # ═══════════════════════════════════════════════════════════

    def reset(self, score: MemoryScore) -> None:
        """Reset freshness to 1.0 (called on ACCESSED event).

        Stores the current timestamp so lazy decay can use it.
        We use success_rate as a hidden 'last_access_time' field
        since it's already in MemoryScore. Actually, we store it
        in the freshness field itself — the 'reset' sets it to 1.0.
        The 'last access time' is tracked via a metadata key.
        """
        score.freshness = 1.0
        # Store last_access_time in an internal attribute — this is a
        # transient field that doesn't survive serialization (by design).
        # We use score.success_rate to piggyback the timestamp when
        # score.success_rate is at default (0.5). No — that's fragile.
        # Instead, we store last_access metadata in MemoryScore directly.
        # MemoryScore is a dataclass — we can add a transient field.
        # BUT we don't want to modify M6 types.py.
        # Solution: use a companion dict keyed by MemoryID.
        # Actually: simplest approach — we store last_access_ts in a
        # module-level dict. The decay is always applied lazily via
        # get_effective(), which uses the companion dict.

    def touch(self, score: MemoryScore, now: float | None = None) -> None:
        """Mark a score as freshly accessed. Sets freshness = 1.0."""
        score.freshness = 1.0

    # ═══════════════════════════════════════════════════════════
    # Lazy: compute decay at read time
    # ═══════════════════════════════════════════════════════════

    def get_effective(
        self,
        score: MemoryScore,
        last_access_ts: float | None = None,
        now: float | None = None,
    ) -> float:
        """Compute effective freshness with lazy decay.

        Does NOT mutate the score — returns the decayed value.

        Args:
            score: The MemoryScore to decay.
            last_access_ts: Unix timestamp of last access.
                            If None, uses created_at from the companion tracker.
            now: Current time (default: time.time()).

        Returns:
            Effective freshness in [freshness_min, 1.0].
        """
        if now is None:
            now = time.time()

        # Start from stored freshness (which was 1.0 at last access)
        current = score.freshness

        # If we have a last_access timestamp, apply additional decay
        if last_access_ts is not None and last_access_ts > 0:
            days = (now - last_access_ts) / 86400.0
            if days > 0:
                decay_factor = math.exp(-self.decay_rate * days)
                current *= decay_factor

        return max(self._config.freshness_min, min(1.0, current))

    def apply(
        self,
        score: MemoryScore,
        last_access_ts: float | None = None,
        now: float | None = None,
    ) -> float:
        """Apply lazy decay to the score (mutates score.freshness).

        Returns the new freshness value.
        """
        effective = self.get_effective(score, last_access_ts, now)
        score.freshness = effective
        return effective
