"""Budget — multi-dimension budget management for Context Engine.

M3 ships with a single "token" budget. The architecture supports
additional dimensions (message_count, duration) in future milestones.
"""

from src.context.budget.manager import Budget, BudgetAllocation, BudgetPolicy, BudgetReport, BudgetManager

__all__ = [
    "Budget",
    "BudgetAllocation",
    "BudgetPolicy",
    "BudgetReport",
    "BudgetManager",
]
