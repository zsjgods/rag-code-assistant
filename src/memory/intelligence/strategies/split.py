"""SplitStrategy — break oversized or overly generic memories into focused parts.

Flow:
  1. Select entries with text length > split_min_text_length
  2. LLM proposes split into 2-5 focused sub-memories
  3. Create child entries, update parent with PARENT/CHILD relations, emit SPLIT

This is a single-entry strategy — entry_b is always None.
The original entry becomes the parent; children are new entries.
"""

from src.memory.intelligence.candidate import StrategyResult
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.strategies.base import ReflectionStrategy


class SplitStrategy(ReflectionStrategy):
    """Break large or generic memories into focused sub-memories."""

    name = "split"

    def select_candidates(self, store, vector_index, embedder, config: IntelligenceConfig):
        if not config.split_enabled:
            return []

        active = store.get_active()
        candidates = []

        for entry in active.values():
            if len(entry.content.text) < config.split_min_text_length:
                continue
            # Single-entry strategy: entry_b is None
            candidates.append((entry, None))

            if len(candidates) >= config.reflection_max_pairs_per_batch:
                break

        return candidates

    def build_prompt(self, entry_a, entry_b, prompt_loader):
        return prompt_loader.load(
            "split_user",
            memory_type=entry_a.type.value,
            memory_summary=entry_a.content.summary,
            memory_content=entry_a.content.text[:1000],
            memory_tags=", ".join(entry_a.content.tags) if entry_a.content.tags else "(none)",
        )

    def parse_result(self, decision: dict, entry_a, entry_b):
        dec = decision.get("decision", "no_split")
        return StrategyResult(
            strategy="split",
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
                "split_parts": {"type": "list"},
            },
        }
