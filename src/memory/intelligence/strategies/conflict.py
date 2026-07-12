"""ConflictStrategy — detect contradictory information in memories.

Flow:
  1. Same coarse filter as MergeStrategy but with lower similarity threshold
  2. LLM judges: "conflict", "superseded", or "distinct"
  3. If conflict: write CONFLICT relation to both entries, emit CONFLICT event
  4. If superseded: write SUPERSEDES/SUPERSEDED_BY relation, emit SUPERSEDED event

Conflict means both may be valid in different contexts.
Superseded means one is clearly an update/replacement of the other.
"""

from src.memory.identity import MemoryID
from src.memory.intelligence.candidate import StrategyResult
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.strategies.base import ReflectionStrategy


class ConflictStrategy(ReflectionStrategy):
    """Detect contradictory or superseding memory pairs."""

    name = "conflict"

    def select_candidates(self, store, vector_index, embedder, config: IntelligenceConfig):
        if not config.conflict_enabled or vector_index is None:
            return []

        active = store.get_active()
        if len(active) < 2:
            return []

        sorted_entries = sorted(
            active.values(),
            key=lambda e: e.score.importance,
            reverse=True,
        )[:config.reflection_max_candidates]

        pairs = []
        seen: set[tuple[str, str]] = set()

        for entry in sorted_entries:
            entry_vec = self._get_embedding(entry, embedder)
            if entry_vec is None:
                continue

            neighbors = vector_index.search(entry_vec, top_k=config.reflection_vector_topk + 1)
            for neighbor_id, similarity in neighbors:
                if neighbor_id == entry.id_str:
                    continue
                if similarity < config.conflict_similarity_threshold:
                    continue

                pair_key = tuple(sorted([entry.id_str, neighbor_id]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                neighbor_entry = store.read(MemoryID(neighbor_id))
                if neighbor_entry is None:
                    continue

                # Only consider pairs that are semantically similar BUT:
                # - Different types (e.g., old DECISION vs new EXPERIENCE)
                # - Or same type with different content
                # Skip if they look like merge candidates (very high similarity)
                if similarity >= config.merge_similarity_threshold:
                    continue  # Let MergeStrategy handle these

                pairs.append((entry, neighbor_entry))

                if len(pairs) >= config.reflection_max_pairs_per_batch:
                    break

            if len(pairs) >= config.reflection_max_pairs_per_batch:
                break

        return pairs

    def build_prompt(self, entry_a, entry_b, prompt_loader):
        return prompt_loader.load(
            "conflict_user",
            memory_a=f"Type: {entry_a.type.value}\nSummary: {entry_a.content.summary}\nContent: {entry_a.content.text[:500]}",
            memory_b=f"Type: {entry_b.type.value}\nSummary: {entry_b.content.summary}\nContent: {entry_b.content.text[:500]}",
        )

    def parse_result(self, decision: dict, entry_a, entry_b):
        dec = decision.get("decision", "distinct")
        return StrategyResult(
            strategy="conflict",
            decision=dec,
            entry_ids=[entry_a.id_str, entry_b.id_str],
            details=decision.get("reason", ""),
        )

    def get_schema(self) -> dict:
        return {
            "required": ["decision", "reason"],
            "properties": {
                "decision": {"type": "str"},
                "reason": {"type": "str", "max": 500},
            },
        }

    @staticmethod
    def _get_embedding(entry, embedder):
        if embedder is None:
            return None
        try:
            text = entry.content.summary or entry.content.text[:200]
            return embedder.embed_query(text)
        except Exception:
            return None
