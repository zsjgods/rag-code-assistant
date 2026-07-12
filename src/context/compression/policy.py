"""CompressionPolicy — decides when to compress based on BudgetReports.

Three-layer separation:
  CompressionRule (ABC) — "what conditions trigger compression"
  OverBudgetRule       — concrete rule: "over-budget → compress"
  CompressionPolicy    — "traverse rules, return the first matching plan"

The Policy has NO business logic if/else. It iterates rules, calls
rule.matches() and rule.to_plan(). All decision logic lives in the rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.context.budget.manager import BudgetReport


# ── CompressionPlan ─────────────────────────────────────────────────────


@dataclass
class CompressionPlan:
    """The sole output of CompressionPolicy — instructs the Pipeline.

    action:       "noop" (nothing to do) | "compress" (execute)
    layer_name:   Which layer to compress (only "conversation" in M3)
    target_tokens: Crunch conversation down to this many tokens
    max_tier:     Maximum allowed compression depth (1-3)
    triggered_by: The BudgetReport that triggered this plan (for observability)
    """

    action: str = "noop"  # "noop" | "compress"
    layer_name: str = ""
    target_tokens: int = 0
    max_tier: int = 3
    triggered_by: BudgetReport | None = None


# ── CompressionRule (abstract) ──────────────────────────────────────────


class CompressionRule(ABC):
    """A single decision rule — matches reports, produces plans.

    Subclasses implement matches() (trigger condition) and to_plan()
    (what to do when triggered).

    Priority controls evaluation order: higher = evaluated first.
    """

    priority: int

    @abstractmethod
    def matches(self, report: BudgetReport) -> bool:
        """Check if this report triggers the rule.

        Pure boolean — no side effects, no state mutation (except
        consecutive counters internal to the rule).
        """
        ...

    @abstractmethod
    def to_plan(self, report: BudgetReport) -> CompressionPlan:
        """Produce a compression plan from the matching report.

        Called only if matches() returned True.
        """
        ...


# ── OverBudgetRule (concrete) ───────────────────────────────────────────


class OverBudgetRule(CompressionRule):
    """Triggers when a specific layer exceeds its budget allocation.

    Supports two guard conditions:
      min_excess_ratio:   Only trigger if excess / limit > this ratio.
                          E.g. 0.20 = only trigger if 20%+ over budget.
      min_consecutive:    Only trigger after N consecutive over-budget reports.
                          Prevents thrashing on borderline cases.

    target_ratio: When triggered, compress down to limit × target_ratio tokens.
                  E.g. 0.50 = compress to 50% of the budget limit.
    """

    def __init__(
        self,
        layer_name: str,
        max_tier: int = 3,
        target_ratio: float = 0.50,
        min_excess_ratio: float = 0.0,
        min_consecutive: int = 1,
        priority: int = 0,
    ):
        self.layer_name = layer_name
        self.max_tier = max_tier
        self.target_ratio = target_ratio
        self.min_excess_ratio = min_excess_ratio
        self.min_consecutive = min_consecutive
        self.priority = priority

        # Internal: consecutive counter (reset on match or miss)
        self._consecutive: int = 0

    def matches(self, report: BudgetReport) -> bool:
        """Check if the report triggers this rule.

        Conditions (all must hold):
          1. Layer name matches
          2. Report is over budget
          3. Excess ratio exceeds min_excess_ratio (if set)
          4. Consecutive count reaches min_consecutive (if > 1)

        Resets the consecutive counter when any condition fails.
        """
        # Condition 1: layer match
        if report.layer_name != self.layer_name:
            self._consecutive = 0
            return False

        # Condition 2: over budget
        if not report.over_budget:
            self._consecutive = 0
            return False

        # Condition 3: minimum excess ratio
        if report.budget_limit > 0 and self.min_excess_ratio > 0:
            excess_ratio = report.excess / report.budget_limit
            if excess_ratio < self.min_excess_ratio:
                self._consecutive = 0
                return False

        # Condition 4: consecutive count
        self._consecutive += 1
        if self._consecutive < self.min_consecutive:
            return False

        return True

    def to_plan(self, report: BudgetReport) -> CompressionPlan:
        """Produce a plan: compress conversation to target_ratio × budget_limit."""
        self._consecutive = 0  # Reset after producing a plan
        return CompressionPlan(
            action="compress",
            layer_name=self.layer_name,
            target_tokens=max(1, int(report.budget_limit * self.target_ratio)),
            max_tier=self.max_tier,
            triggered_by=report,
        )


# ── CompressionPolicy ───────────────────────────────────────────────────


class CompressionPolicy:
    """Evaluates BudgetReports against a set of rules.

    Evaluation order:
      1. Rules are sorted by priority (highest first) on each evaluate()
      2. For each rule, iterate reports in order
      3. First rule.matches(report) == True wins
      4. Return rule.to_plan(report)

    No if/else business logic — pure rule traversal.
    No rules = always returns noop (safe default).
    """

    def __init__(self):
        self._rules: list[CompressionRule] = []

    def add_rule(self, rule: CompressionRule) -> None:
        """Register a decision rule.

        Rules are sorted by priority on each evaluate() call,
        so insertion order and caller preferences don't matter.
        """
        self._rules.append(rule)

    @property
    def rules(self) -> list[CompressionRule]:
        """All registered rules (sorted by priority descending)."""
        return sorted(self._rules, key=lambda r: r.priority, reverse=True)

    def evaluate(self, reports: list[BudgetReport]) -> CompressionPlan:
        """Evaluate reports against all rules.

        Returns the first matching rule's plan, or noop.

        Args:
            reports: BudgetReports from BudgetManager.check()

        Returns:
            CompressionPlan — either "noop" or "compress" with details.
        """
        # Always sort by priority to be order-independent
        sorted_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            for report in reports:
                if rule.matches(report):
                    return rule.to_plan(report)

        return CompressionPlan(action="noop")
