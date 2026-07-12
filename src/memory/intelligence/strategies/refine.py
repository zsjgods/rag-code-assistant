"""RefineStrategy — improve summary and tags for high-value memories.

Flow:
  1. Select entries with importance > refine_min_importance and age > refine_min_age_days
  2. LLM proposes better summary and tags (single entry, no pair)
  3. Update entry in-place, emit UPDATED event

This is a single-entry strategy — entry_b is always None.
"""

import time

from src.memory.intelligence.candidate import StrategyResult
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.strategies.base import ReflectionStrategy


class RefineStrategy(ReflectionStrategy):
    """Improve summary and tags for important, aging memories."""

    name = "refine"

    def select_candidates(self, store, vector_index, embedder, config: IntelligenceConfig):
        if not config.refine_enabled:
            return []

        active = store.get_active()
        now = time.time()
        min_age_seconds = config.refine_min_age_days * 86400.0

        candidates = []
        for entry in active.values():
            if entry.score.importance < config.refine_min_importance:
                continue
            age = now - entry.identity.created_at
            if age < min_age_seconds:
                continue
            # Single-entry strategy: entry_b is None
            candidates.append((entry, None))

            if len(candidates) >= config.reflection_max_pairs_per_batch:
                break

        return candidates

    def build_prompt(self, entry_a, entry_b, prompt_loader):
        return prompt_loader.load(
            "refine_user",
            memory_type=entry_a.type.value,
            memory_summary=entry_a.content.summary,
            memory_content=entry_a.content.text[:800],
            memory_tags=", ".join(entry_a.content.tags) if entry_a.content.tags else "(none)",
        )

    def parse_result(self, decision: dict, entry_a, entry_b):
        dec = decision.get("decision", "no_change")
        return StrategyResult(
            strategy="refine",
            decision=dec,
            entry_ids=[entry_a.id_str],
            details=decision.get("reason", ""),
        )

    def get_schema(self) -> dict:
        return {
            "required": ["decision", "reason"],
            "properties": {
                "decision": {"type": "str"},
                "reason": {"type": "str", "max": 500},
                "refined_summary": {"type": "str", "max": 300},
                "refined_tags": {"type": "list"},
            },
        }
