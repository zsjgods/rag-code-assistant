"""M9 Reflection Strategies.

Each strategy operates independently:
  - MergeStrategy    — find duplicate/similar pairs, propose merges
  - ConflictStrategy — detect contradictory information
  - RefineStrategy   — improve summary/tags for high-value entries
  - SplitStrategy    — break large entries into smaller focused ones

All strategies share the same ABC: ReflectionStrategy.
"""

from src.memory.intelligence.strategies.base import ReflectionStrategy
from src.memory.intelligence.strategies.conflict import ConflictStrategy
from src.memory.intelligence.strategies.merge import MergeStrategy
from src.memory.intelligence.strategies.refine import RefineStrategy
from src.memory.intelligence.strategies.split import SplitStrategy

__all__ = [
    "ReflectionStrategy",
    "MergeStrategy",
    "ConflictStrategy",
    "RefineStrategy",
    "SplitStrategy",
]
