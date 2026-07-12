"""LifecycleConfig — all tunable parameters for M10 Lifecycle Engine."""

from dataclasses import dataclass, field


@dataclass
class LifecycleConfig:
    """All tunable parameters for M10 Lifecycle & Operations."""

    # ── State Transition ──
    state_warm_threshold: float = 0.50       # Score threshold for WARM
    state_cold_threshold: float = 0.25       # Score threshold for COLD
    state_archive_threshold: float = 0.10    # Score threshold for ARCHIVE
    state_max_age_days: float = 365.0        # Max age considered in decay

    # State scoring weights (must sum to ~1.0)
    state_w_importance: float = 0.35
    state_w_frequency: float = 0.25
    state_w_freshness: float = 0.25
    state_w_age: float = 0.15

    # ── Archive ──
    archive_enabled: bool = True
    archive_importance_threshold: float = 0.15
    archive_min_age_days: float = 180.0
    archive_max_frequency: int = 1           # Archive if accessed ≤ this many times
    archive_freshness_threshold: float = 0.05

    # ── Compression ──
    compression_enabled: bool = True
    compression_strategy: str = "rule"       # "rule" | "llm" | "hybrid"
    compression_min_group_size: int = 3
    compression_max_group_size: int = 20
    compression_similarity_threshold: float = 0.75
    compression_same_type_only: bool = True

    # ── Retention (Purge) ──
    retention_enabled: bool = False          # Default OFF — explicit opt-in
    retention_max_archived_age_days: float = 365.0
    retention_purge_importance_threshold: float = 0.05

    # ── GC ──
    gc_enabled: bool = True
    gc_clean_orphan_relations: bool = True
    gc_validate_broken_refs: bool = True
    gc_repair_duplicates: bool = True

    # ── Scheduler ──
    scheduler_enabled: bool = True
    scheduler_cycle_seconds: float = 600.0   # 10 minutes
    scheduler_worker_batch_size: int = 10
    scheduler_worker_flush_interval: float = 5.0
    scheduler_worker_max_retries: int = 3
