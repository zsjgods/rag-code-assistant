"""M8 Importance Engine — dynamic memory scoring.

Components:
  - ImportanceEngine  — facade, assembles all components
  - ImportanceScorer  — type_weight × source_weight + sigmoid boost
  - FreshnessDecay    — lazy + event-driven exponential decay
  - AccessTracker     — subscribe ACCESSED → update frequency/freshness/importance
  - FeedbackHandler   — explicit feedback → update confidence/success_rate
  - VacuumPolicy      — low-value detection → VACUUMED
  - ImportanceConfig  — all tunable parameters

Usage:
    from src.memory.importance import ImportanceEngine, ImportanceConfig

    config = ImportanceConfig()
    config.freshness_half_life_days = 14.0

    engine = ImportanceEngine(store, events, config)
    engine.start()
"""

from src.memory.importance.config import ImportanceConfig
from src.memory.importance.decay import FreshnessDecay
from src.memory.importance.engine import ImportanceEngine
from src.memory.importance.feedback import FeedbackHandler
from src.memory.importance.scoring import ImportanceScorer
from src.memory.importance.tracking import AccessTracker
from src.memory.importance.vacuum import VacuumPolicy

__all__ = [
    "ImportanceEngine",
    "ImportanceConfig",
    "ImportanceScorer",
    "FreshnessDecay",
    "AccessTracker",
    "FeedbackHandler",
    "VacuumPolicy",
]
