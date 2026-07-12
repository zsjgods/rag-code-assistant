"""SelectionPolicy — applies constraints to prune Candidates.

Policy decides which candidates survive and which are discarded.
Like all M4 components, it never modifies Candidate objects — it returns
new (selected, discarded) tuples.

M4 ships with BudgetSelectionPolicy (token-based constraint).
Future policies (LatencyConstraint, CostConstraint) can be added
without changing the Pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.context.selection.candidate import Candidate


# ── TokenConstraint ────────────────────────────────────────────────────


@dataclass
class TokenConstraint:
    """A token budget for one source.

    source:     Layer name this constraint applies to ("conversation", etc.)
    max_tokens: Maximum tokens this source may contribute.
    reserved:   If True, this source is always included (up to max_tokens).
                Reserved sources are counted first and never compete.
    """

    source: str
    max_tokens: int
    reserved: bool = False


# ── SelectionPolicy (ABC) ──────────────────────────────────────────────


class SelectionPolicy(ABC):
    """Filters Candidates by applying constraints.

    Returns (selected, discarded) — two new lists.
    Never modifies input Candidates.
    """

    @abstractmethod
    def select(self, candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
        ...


# ── BudgetSelectionPolicy ──────────────────────────────────────────────


class BudgetSelectionPolicy(SelectionPolicy):
    """Token-budget-based selection with reserved sources.

    Algorithm:
      1. Reserved sources (instruction, workspace) are always fully included.
      2. Remaining budget is distributed to non-reserved candidates in order.
      3. Candidates that don't fit are marked discarded.

    Candidates are expected to already be sorted by priority/recency
    (the Pipeline runs Ranker before Policy).
    """

    def __init__(self, constraints: list[TokenConstraint], total_budget: int = 0):
        """
        Args:
            constraints: Per-source token constraints.
            total_budget: Global hard cap (0 = sum of all max_tokens).
        """
        self._constraints: dict[str, TokenConstraint] = {
            c.source: c for c in constraints
        }
        self._total_budget = total_budget or sum(c.max_tokens for c in constraints)

    @property
    def constraints(self) -> list[TokenConstraint]:
        return list(self._constraints.values())

    def select(self, candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
        selected: list[Candidate] = []
        discarded: list[Candidate] = []

        # Track per-source token usage
        usage: dict[str, int] = {}
        total_used = 0

        # Phase 1: reserved sources (instruction, workspace)
        for c in candidates:
            constraint = self._constraints.get(c.layer_name)
            if constraint and constraint.reserved:
                source_used = usage.get(c.layer_name, 0)
                room = constraint.max_tokens - source_used
                if c.token_count <= room and total_used + c.token_count <= self._total_budget:
                    selected.append(c)
                    usage[c.layer_name] = source_used + c.token_count
                    total_used += c.token_count
                else:
                    discarded.append(c)

        # Phase 2: non-reserved sources (in rank order)
        for c in candidates:
            constraint = self._constraints.get(c.layer_name)
            if not constraint or constraint.reserved:
                continue  # Already handled in phase 1

            source_used = usage.get(c.layer_name, 0)
            room = constraint.max_tokens - source_used

            if c.token_count <= room and total_used + c.token_count <= self._total_budget:
                selected.append(c)
                usage[c.layer_name] = source_used + c.token_count
                total_used += c.token_count
            else:
                discarded.append(c)

        return selected, discarded
