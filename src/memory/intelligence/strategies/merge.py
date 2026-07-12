"""MergeStrategy — find and merge duplicate/similar memories.

Flow:
  1. Select top-N entries by importance
  2. For each, vector_index.search(top_k=5) for semantic neighbors
  3. Filter pairs with cosine similarity > merge_similarity_threshold
  4. LLM judges: "merge" or "distinct"
  5. If merge: create new merged entry, archive old pair, emit MERGED
"""

from src.memory.identity import MemoryID
from src.memory.intelligence.candidate import StrategyResult
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.relation_types import RelationType, apply_relation_pair
from src.memory.intelligence.strategies.base import ReflectionStrategy


class MergeStrategy(ReflectionStrategy):
    """Detect and merge duplicate/similar memory entries."""

    name = "merge"

    def select_candidates(self, store, vector_index, embedder, config: IntelligenceConfig):
        if not config.merge_enabled or vector_index is None:
            return []

        active = store.get_active()
        if len(active) < 2:
            return []

        # Sort by importance desc, take top-N
        sorted_entries = sorted(
            active.values(),
            key=lambda e: e.score.importance,
            reverse=True,
        )[:config.reflection_max_candidates]

        pairs = []
        seen: set[tuple[str, str]] = set()

        for entry in sorted_entries:
            # Get embedding for this entry
            entry_vec = self._get_embedding(entry, embedder)
            if entry_vec is None:
                continue

            # Search for similar entries
            neighbors = vector_index.search(entry_vec, top_k=config.reflection_vector_topk + 1)
            for neighbor_id, similarity in neighbors:
                if neighbor_id == entry.id_str:
                    continue
                if similarity < config.merge_similarity_threshold:
                    continue

                # Avoid duplicate pairs (a,b) and (b,a)
                pair_key = tuple(sorted([entry.id_str, neighbor_id]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                neighbor_entry = store.read(MemoryID(neighbor_id))
                if neighbor_entry is None:
                    continue

                pairs.append((entry, neighbor_entry))

                if len(pairs) >= config.reflection_max_pairs_per_batch:
                    break

            if len(pairs) >= config.reflection_max_pairs_per_batch:
                break

        return pairs

    def build_prompt(self, entry_a, entry_b, prompt_loader):
        return prompt_loader.load(
            "merge_user",
            memory_a=f"Type: {entry_a.type.value}\nSummary: {entry_a.content.summary}\nContent: {entry_a.content.text[:500]}",
            memory_b=f"Type: {entry_b.type.value}\nSummary: {entry_b.content.summary}\nContent: {entry_b.content.text[:500]}",
        )

    def parse_result(self, decision: dict, entry_a, entry_b):
        dec = decision.get("decision", "distinct")
        return StrategyResult(
            strategy="merge",
            decision=dec,
            entry_ids=[entry_a.id_str, entry_b.id_str],
            new_entry_id=entry_a.id_str if dec == "merge" else None,
            details=decision.get("reason", ""),
        )

    def get_schema(self) -> dict:
        return {
            "required": ["decision", "reason"],
            "properties": {
                "decision": {"type": "str"},
                "reason": {"type": "str", "max": 500},
                "merged_text": {"type": "str", "max": 5000},
                "merged_summary": {"type": "str", "max": 200},
                "merged_tags": {"type": "list"},
            },
        }

    @staticmethod
    def _get_embedding(entry, embedder):
        """Get embedding vector for an entry. Returns None if unavailable."""
        if embedder is None:
            return None
        try:
            text = entry.content.summary or entry.content.text[:200]
            return embedder.embed_query(text)
        except Exception:
            return None
