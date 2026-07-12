"""ImportanceConfig — all tunable parameters for M8 Importance Engine."""

from dataclasses import dataclass, field


@dataclass
class ImportanceConfig:
    """All tunable parameters for the M8 Importance Engine.

    Usage:
        config = ImportanceConfig()
        config.type_weights["decision"] = 0.9

        engine = ImportanceEngine(store, events, config=config)
    """

    # ── Type weights (importance baseline per MemoryType) ──
    type_weights: dict[str, float] = field(default_factory=lambda: {
        "decision": 0.85,
        "experience": 0.75,
        "tool": 0.65,
        "code": 0.55,
        "knowledge": 0.50,
        "project": 0.50,
        "user": 0.55,
        "conversation": 0.40,
    })

    # ── Source weights (multiplier for importance baseline) ──
    source_weights: dict[str, float] = field(default_factory=lambda: {
        "manual": 1.0,
        "agent": 0.7,
        "system": 0.5,
    })

    # ── Access boost ──
    access_boost: float = 0.01  # Importance increment per access
    access_boost_cap: float = 0.95  # Sigmoid ceiling for access boost
    access_boost_k: float = 10.0  # Sigmoid steepness

    # ── Freshness decay ──
    freshness_half_life_days: float = 30.0  # Half-life for exponential decay
    freshness_min: float = 0.01  # Floor value (never reach absolute zero)

    # ── Feedback adjustments ──
    feedback_useful_confidence_delta: float = 0.10
    feedback_useful_success_rate_alpha: float = 0.3  # EMA smoothing factor
    feedback_not_useful_importance_delta: float = -0.10
    feedback_not_useful_confidence_delta: float = -0.10
    feedback_critical_importance_floor: float = 0.90
    feedback_critical_confidence_floor: float = 0.90

    # ── Vacuum ──
    vacuum_enabled: bool = True
    vacuum_importance_threshold: float = 0.15
    vacuum_min_age_days: float = 7.0
    vacuum_auto_archive: bool = False  # If True, auto-archive low-value entries

    # ── Override ──
    override_on_create: bool = True  # Auto-set importance from type × source on CREATED
    only_override_default: bool = True  # Only override if importance == 0.5 (the default)
