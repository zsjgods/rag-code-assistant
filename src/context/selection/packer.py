"""Packer — resolves Candidate references into a structured PromptPackage.

Packer is the bridge between "what was selected" and "what the LLM sees."
It calls Collector.resolve() for each selected candidate and assembles
the results into a PromptPackage (structured, not pre-rendered).

PromptPackage is the SOLE data exchange object in the entire Context Engine.
PromptBuilder, Debugger, Recovery, and Observability all read PromptPackage.
"""

from dataclasses import dataclass, field
from typing import Any

from src.context.selection.candidate import Candidate
from src.context.selection.collector import Collector, SelectionContext


# ── SelectionStats ─────────────────────────────────────────────────────


@dataclass
class SelectionStats:
    """Formal runtime statistics for one pipeline execution.

    M5 Observability reads this directly — no dict key guessing.
    """

    total_candidates: int = 0
    selected_candidates: int = 0
    discarded_candidates: int = 0
    collect_time_ms: float = 0.0
    rank_time_ms: float = 0.0
    policy_time_ms: float = 0.0
    pack_time_ms: float = 0.0
    total_time_ms: float = 0.0
    tokens_before: int = 0
    tokens_after: int = 0


# ── PromptPackage ──────────────────────────────────────────────────────


@dataclass
class PromptPackage:
    """Structured prompt content — NOT pre-rendered.

    system_parts:  List of str blocks → joined by PromptBuilder
    message_parts: List of list[dict] blocks → flattened by PromptBuilder
    token_usage:   Per-source token count (layer_name → tokens)
    total_tokens:  Sum of token_usage values

    PromptBuilder is the ONLY component that joins these into the final format.
    """

    system_parts: list[str] = field(default_factory=list)
    message_parts: list[list[dict]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0


# ── SelectionResult ────────────────────────────────────────────────────


@dataclass
class SelectionResult:
    """Complete pipeline output.

    .package    → consumed by PromptBuilder
    .selected   → all chosen Candidates (for debug/observability)
    .discarded  → all pruned Candidates (for debug/observability)
    .stats      → runtime metrics (for M5 Observability)
    """

    package: PromptPackage
    selected: list[Candidate]
    discarded: list[Candidate]
    stats: SelectionStats


# ── Packer ─────────────────────────────────────────────────────────────


class Packer:
    """Assembles selected Candidates into a PromptPackage.

    For each selected candidate:
      1. Find its Collector (by layer_name)
      2. Call collector.resolve(candidate, ctx)
      3. Route content to system_parts (str) or message_parts (list[dict])
      4. Track token usage
    """

    def pack(
        self,
        selected: list[Candidate],
        collectors: dict[str, Collector],
        ctx: SelectionContext,
    ) -> PromptPackage:
        system_parts: list[str] = []
        message_parts: list[list[dict]] = []
        usage: dict[str, int] = {}

        for c in selected:
            collector = collectors.get(c.layer_name)
            if collector is None:
                continue

            content = collector.resolve(c, ctx)
            usage[c.layer_name] = usage.get(c.layer_name, 0) + c.token_count

            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                message_parts.append(content)

        return PromptPackage(
            system_parts=system_parts,
            message_parts=message_parts,
            token_usage=usage,
            total_tokens=sum(usage.values()),
        )
