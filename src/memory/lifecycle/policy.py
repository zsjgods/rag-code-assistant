"""Lifecycle Policy Engine — unified policy management for M10.

Four policies, all driven by LifecycleConfig:
  - StateTransitionPolicy — weighted scoring for ACTIVE↔WARM↔COLD↔ARCHIVED
  - ArchivePolicy         — when to archive entries
  - CompressionPolicy     — when and how to compress groups
  - RetentionPolicy       — when to purge (opt-in, off by default)

Usage:
    policy = LifecyclePolicyEngine(config)
    new_state = policy.state.evaluate(entry, days_since_access)
"""

import time
from abc import ABC, abstractmethod

from src.memory.lifecycle.config import LifecycleConfig
from src.memory.types import MemoryEntry, MemoryState


# ═══════════════════════════════════════════════════════════════════
# StateTransitionPolicy
# ═══════════════════════════════════════════════════════════════════

class StateTransitionPolicy:
    """Weighted scoring for state transitions. NO hardcoded days.

    score = w_imp * importance + w_freq * norm_freq + w_fresh * freshness + w_age * norm_age
    score ∈ [0, 1] → mapped to state via thresholds.

    Default weights: importance 0.35, frequency 0.25, freshness 0.25, age 0.15
    """

    def __init__(self, config: LifecycleConfig):
        self._cfg = config

    def evaluate(self, entry: MemoryEntry, days_since_access: float = 0.0) -> MemoryState:
        """Compute weighted score and map to state."""
        score = self._compute_score(entry, days_since_access)

        if score >= self._cfg.state_warm_threshold:
            return MemoryState.ACTIVE
        elif score >= self._cfg.state_cold_threshold:
            return MemoryState.WARM
        elif score >= self._cfg.state_archive_threshold:
            return MemoryState.COLD
        else:
            return MemoryState.ARCHIVED

    def _compute_score(self, entry: MemoryEntry, days_since_access: float) -> float:
        """Weighted sum of normalized dimensions."""
        imp = entry.score.importance

        # Normalize frequency: 0 accesses → 0, 10+ → 1.0
        freq = min(1.0, entry.score.frequency / 10.0)

        # Freshness is already 0-1
        fresh = entry.score.freshness

        # Age factor: newer = higher score. 0 days → 1.0, max_age_days → 0
        age_factor = 1.0 - min(1.0, days_since_access / self._cfg.state_max_age_days)

        score = (
            self._cfg.state_w_importance * imp +
            self._cfg.state_w_frequency * freq +
            self._cfg.state_w_freshness * fresh +
            self._cfg.state_w_age * age_factor
        )
        return max(0.0, min(1.0, score))


# ═══════════════════════════════════════════════════════════════════
# ArchivePolicy
# ═══════════════════════════════════════════════════════════════════

class ArchivePolicy:
    """Decide when to archive entries based on configurable rules."""

    def __init__(self, config: LifecycleConfig):
        self._cfg = config

    def should_archive(self, entry: MemoryEntry, days_since_access: float = 0.0) -> tuple[bool, str]:
        """Check if an entry should be archived.

        Returns (should_archive, reason).
        """
        if not self._cfg.archive_enabled:
            return False, "archive disabled"

        # Rule 1: Low importance + old enough
        if (entry.score.importance < self._cfg.archive_importance_threshold and
                days_since_access >= self._cfg.archive_min_age_days):
            return True, f"low importance ({entry.score.importance:.2f}) + old ({days_since_access:.0f}d)"

        # Rule 2: Never accessed + old enough
        if (entry.score.frequency <= self._cfg.archive_max_frequency and
                days_since_access >= self._cfg.archive_min_age_days):
            return True, f"never accessed + old ({days_since_access:.0f}d)"

        # Rule 3: Extremely decayed freshness
        if entry.score.freshness < self._cfg.archive_freshness_threshold:
            return True, f"freshness decayed ({entry.score.freshness:.3f})"

        return False, ""


# ═══════════════════════════════════════════════════════════════════
# CompressionPolicy
# ═══════════════════════════════════════════════════════════════════

class CompressionPolicy:
    """Decide when and how to compress memory groups."""

    def __init__(self, config: LifecycleConfig):
        self._cfg = config

    def should_compress(self, group: list[MemoryEntry]) -> tuple[bool, str]:
        """Check if a group should be compressed.

        Returns (should_compress, reason).
        """
        if not self._cfg.compression_enabled:
            return False, "compression disabled"

        if len(group) < self._cfg.compression_min_group_size:
            return False, f"group too small: {len(group)} < {self._cfg.compression_min_group_size}"

        if len(group) > self._cfg.compression_max_group_size:
            return False, f"group too large: {len(group)} > {self._cfg.compression_max_group_size}"

        if self._cfg.compression_same_type_only:
            types = {e.type for e in group}
            if len(types) > 1:
                return False, f"mixed types: {types}"

        return True, ""

    @property
    def strategy(self) -> str:
        return self._cfg.compression_strategy

    @property
    def similarity_threshold(self) -> float:
        return self._cfg.compression_similarity_threshold


# ═══════════════════════════════════════════════════════════════════
# RetentionPolicy
# ═══════════════════════════════════════════════════════════════════

class RetentionPolicy:
    """Decide when to permanently purge entries. Off by default."""

    def __init__(self, config: LifecycleConfig):
        self._cfg = config

    def should_purge(self, entry: MemoryEntry, days_since_archived: float = 0.0) -> tuple[bool, str]:
        """Check if an archived entry should be permanently purged.

        This is IRREVERSIBLE. Only applies to ARCHIVED or DELETED entries.
        Never purges ACTIVE/WARM/COLD entries.

        Returns (should_purge, reason).
        """
        if not self._cfg.retention_enabled:
            return False, "retention disabled"

        if entry.state not in (MemoryState.ARCHIVED, MemoryState.DELETED):
            return False, f"not purgable state: {entry.state.value}"

        # Archived too long
        if days_since_archived > self._cfg.retention_max_archived_age_days:
            return True, f"archived too long: {days_since_archived:.0f}d"

        # Importance near zero
        if entry.score.importance < self._cfg.retention_purge_importance_threshold:
            return True, f"importance too low: {entry.score.importance:.3f}"

        return False, ""


# ═══════════════════════════════════════════════════════════════════
# LifecyclePolicyEngine
# ═══════════════════════════════════════════════════════════════════

class LifecyclePolicyEngine:
    """Unified policy management for M10 Lifecycle.

    All policies are loaded from a single LifecycleConfig and can be
    hot-updated by replacing the config reference.

    Usage:
        engine = LifecyclePolicyEngine(config)
        new_state = engine.state.evaluate(entry, days)
        should, reason = engine.archive.should_archive(entry, days)
    """

    def __init__(self, config: LifecycleConfig | None = None):
        cfg = config or LifecycleConfig()
        self.state = StateTransitionPolicy(cfg)
        self.archive = ArchivePolicy(cfg)
        self.compression = CompressionPolicy(cfg)
        self.retention = RetentionPolicy(cfg)
        self._config = cfg

    def update_config(self, config: LifecycleConfig) -> None:
        """Hot-update all policies with new config."""
        self._config = config
        self.state = StateTransitionPolicy(config)
        self.archive = ArchivePolicy(config)
        self.compression = CompressionPolicy(config)
        self.retention = RetentionPolicy(config)
