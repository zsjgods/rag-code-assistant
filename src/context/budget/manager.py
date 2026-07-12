"""BudgetManager — pure-fact budget calculation for the Context Engine.

Single responsibility: "how many tokens does each layer have, and how many
are they using?" Returns BudgetReport (a fact). Makes no decisions.

Supports multiple budget dimensions (budget_name) for future extensibility.
M3 only uses "token".
"""

from dataclasses import dataclass, field
from typing import Any

from src.context.layers.base import BaseLayer


# ── Budget dimensions ────────────────────────────────────────────────────


@dataclass
class Budget:
    """A budget dimension (e.g. token budget, message count limit).

    M3 only uses Budget(name="token", total=180000).
    """

    name: str           # "token"
    total: int | float  # Total capacity (tokens, count, etc.)
    unit: str           # Display unit ("tokens", "messages", "seconds")


# ── Allocation definitions ───────────────────────────────────────────────


@dataclass
class BudgetAllocation:
    """One layer's share of a budget dimension.

    layer_name: which layer this allocation applies to
    ratio:      fraction of the total budget (0.0–1.0)
    """

    layer_name: str
    ratio: float


class BudgetPolicy:
    """Defines how budget is distributed across layers.

    Pure definition — stores allocation ratios, provides lookup.
    Does NOT reference any Layer instance or token count.

    Supports multiple budget dimensions:
      policy = BudgetPolicy()
      policy.add(BudgetAllocation("conversation", 0.60), budget_name="token")
      policy.add(BudgetAllocation("summary", 0.20), budget_name="token")
    """

    def __init__(self, allocations: list[BudgetAllocation] | None = None):
        # budget_name → list[BudgetAllocation]
        self._allocations: dict[str, list[BudgetAllocation]] = {}
        if allocations:
            for alloc in allocations:
                self.add(alloc)

    def add(self, allocation: BudgetAllocation, budget_name: str = "token") -> None:
        """Register an allocation for a layer under the given budget."""
        if budget_name not in self._allocations:
            self._allocations[budget_name] = []
        self._allocations[budget_name].append(allocation)

    def get_limit(self, budget_name: str, total: int | float, layer_name: str) -> int:
        """Calculate the token/count limit for a specific layer.

        Returns 0 if no allocation is registered for that layer+budget combo.
        """
        allocs = self._allocations.get(budget_name, [])
        for alloc in allocs:
            if alloc.layer_name == layer_name:
                return int(total * alloc.ratio)
        return 0

    def get_ratio(self, budget_name: str, layer_name: str) -> float:
        """Return the allocation ratio for a layer, or 0.0 if not found."""
        allocs = self._allocations.get(budget_name, [])
        for alloc in allocs:
            if alloc.layer_name == layer_name:
                return alloc.ratio
        return 0.0

    def remove(self, layer_name: str, budget_name: str = "token") -> bool:
        """Remove a layer's allocation. Returns True if found."""
        allocs = self._allocations.get(budget_name, [])
        for i, alloc in enumerate(allocs):
            if alloc.layer_name == layer_name:
                allocs.pop(i)
                return True
        return False

    def list_allocations(self, budget_name: str = "token") -> list[BudgetAllocation]:
        """Return all allocations for a budget dimension."""
        return list(self._allocations.get(budget_name, []))


# ── Reports ──────────────────────────────────────────────────────────────


@dataclass
class BudgetReport:
    """A single budget fact — produced by BudgetManager for one Layer × Budget.

    This is the ONLY output of BudgetManager. Consumers (CompressionPolicy)
    read these facts to decide whether to act.
    """

    budget_name: str     # "token"
    layer_name: str      # "conversation"
    token_count: int     # Actual usage from layer.token_count()
    budget_limit: int    # Allocated limit from BudgetPolicy.get_limit()
    over_budget: bool    # token_count > budget_limit (the only boolean judgment)
    excess: int          # token_count - budget_limit (negative = headroom)

    @property
    def usage_ratio(self) -> float:
        """Fraction of budget consumed (0.0–1.0+)."""
        if self.budget_limit <= 0:
            return 0.0
        return self.token_count / self.budget_limit


# ── BudgetManager ────────────────────────────────────────────────────────


class BudgetManager:
    """Pure-fact budget calculator.

    Responsibilities:
      - Maintain budget dimensions (Budget × total)
      - Maintain allocation policy for each dimension
      - Check layers against their allocations → list[BudgetReport]

    Non-responsibilities:
      - Deciding whether to compress (→ CompressionPolicy)
      - Performing compression (→ CompressionPipeline)
      - Holding references to Layer instances (layers are passed to check())
    """

    def __init__(self, budgets: list[Budget], policy: BudgetPolicy):
        """
        Args:
            budgets: Supported budget dimensions.
                     M3: [Budget(name="token", total=180000, unit="tokens")]
            policy:  Allocation policy for each budget dimension.
        """
        self._budgets: dict[str, Budget] = {b.name: b for b in budgets}
        self._policy = policy

    @property
    def policy(self) -> BudgetPolicy:
        """The allocation policy (allows runtime adjustments)."""
        return self._policy

    @property
    def budgets(self) -> list[Budget]:
        """All registered budget dimensions."""
        return list(self._budgets.values())

    # ── Checking ────────────────────────────────────────

    def check(self, layers: list[BaseLayer]) -> list[BudgetReport]:
        """Check all layers against all budget dimensions.

        Returns one report per (layer, budget) combination.
        Layers with no allocation for a given budget are skipped.
        """
        reports: list[BudgetReport] = []
        for budget_name, budget in self._budgets.items():
            for layer in layers:
                report = self._check_layer(budget_name, budget.total, layer)
                if report is not None:
                    reports.append(report)
        return reports

    def check_layer(self, layer: BaseLayer, budget_name: str = "token") -> BudgetReport | None:
        """Check a single layer against a specific budget dimension.

        Returns None if the layer has no allocation.
        """
        budget = self._budgets.get(budget_name)
        if budget is None:
            return None
        return self._check_layer(budget_name, budget.total, layer)

    def _check_layer(self, budget_name: str, total: int | float, layer: BaseLayer) -> BudgetReport | None:
        limit = self._policy.get_limit(budget_name, total, layer.name)
        if limit <= 0 and self._policy.get_ratio(budget_name, layer.name) <= 0:
            return None  # No allocation for this layer
        used = layer.token_count()
        return BudgetReport(
            budget_name=budget_name,
            layer_name=layer.name,
            token_count=used,
            budget_limit=limit,
            over_budget=used > limit,
            excess=used - limit,
        )

    # ── Runtime adjustments ─────────────────────────────

    def set_allocation(self, layer_name: str, ratio: float, budget_name: str = "token") -> None:
        """Add or update a layer's budget allocation at runtime.

        M4 dynamic budget adjustment uses this.
        """
        self._policy.remove(layer_name, budget_name)
        self._policy.add(BudgetAllocation(layer_name, ratio), budget_name)
