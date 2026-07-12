"""Ranker — sorts Candidates for the Context Selection Pipeline.

Ranker never modifies Candidates (they're frozen). It returns new sorted lists.
Priority is external to Candidate — provided by PriorityProvider.
"""

from abc import ABC, abstractmethod

from src.context.selection.candidate import Candidate


class PriorityProvider:
    """Maps source name → priority integer.

    Lower values = higher priority.
    This is a pluggable strategy — swap it out without changing Ranker.

    Default mapping:
      instruction:  0  (reserved, always kept)
      workspace:    1
      memory:       2  (M6)
      summary:      2
      file_cache:   3
      conversation: 4
    """

    def __init__(self, priorities: dict[str, int] | None = None):
        self._map = dict(priorities or {
            "instruction": 0,
            "workspace": 1,
            "memory": 2,  # M6
            "summary": 2,
            "file_cache": 3,
            "conversation": 4,
        })

    def get(self, layer_name: str) -> int:
        """Return priority for a source. Unknown sources get lowest priority."""
        return self._map.get(layer_name, 99)

    def set(self, layer_name: str, priority: int) -> None:
        """Add or update a source's priority at runtime."""
        self._map[layer_name] = priority

    def remove(self, layer_name: str) -> None:
        """Remove a source from the priority map."""
        self._map.pop(layer_name, None)


class Ranker(ABC):
    """Sorts Candidates. Returns new lists, never modifies input."""

    @abstractmethod
    def rank(self, candidates: list[Candidate]) -> list[Candidate]:
        ...


class PriorityRanker(Ranker):
    """Sorts by (priority, -recency).

    Primary key: priority (lower = higher priority, 0 = reserved)
    Secondary key: recency (higher = newer, for same-priority sources)
    """

    def __init__(self, provider: PriorityProvider | None = None):
        self._provider = provider or PriorityProvider()

    @property
    def provider(self) -> PriorityProvider:
        return self._provider

    def rank(self, candidates: list[Candidate]) -> list[Candidate]:
        return sorted(
            candidates,
            key=lambda c: (self._provider.get(c.layer_name), -c.recency),
        )
