"""MemoryCollector — M4 Context Selection Pipeline adapter.

Provides Candidate extraction for the Memory layer so that the
BudgetSelectionPolicy can control how many tokens memory context consumes.

Follows the same pattern as WorkspaceCollector: one candidate representing
the entire layer output.

Phase 1: Direct store access (same degradation as MemoryLayer).
Phase 2: Upgrade to Planner → Retrieval → Store chain.
"""

from src.context.selection.collector import Collector, SelectionContext, Candidate


class MemoryCollector(Collector):
    """M4 Selection Pipeline collector for memory entries.

    Produces a single candidate representing the full <memory-context> block.
    The BudgetSelectionPolicy then decides how many tokens to allocate.

    Usage:
        collector = MemoryCollector(store=store)
        # Add to SelectionPipeline collectors list
    """

    source_name = "memory"

    def __init__(self, store=None):
        """Initialize the memory collector.

        Args:
            store: MemoryStore instance.
        """
        self._store = store

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        """Collect one candidate representing the full memory context.

        If no MemoryStore is configured or no active entries exist, returns empty list.
        """
        if self._store is None:
            return []

        active = self._store.get_active()
        if not active:
            return []

        # Estimate total token count of the rendered memory context
        total_text = " ".join(
            e.content.summary or e.content.text[:100] for e in active.values()
        )
        estimated_tokens = max(1, len(total_text) // 4)

        return [Candidate(
            layer_name="memory",
            item_id="context",
            recency=max(
                (e.identity.created_at for e in active.values()),
                default=0.0,
            ),
            token_count=estimated_tokens,
            importance=0.6,  # Memory is useful but not critical
            metadata={
                "entry_count": len(active),
                "types": list({e.type.value for e in active.values()}),
            },
        )]

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> str:
        """Resolve the memory candidate to rendered content.

        Delegates to the MemoryLayer if available via SelectionContext,
        otherwise does a simple fallback render.
        """
        # Try to use the MemoryLayer from context
        memory_layer = getattr(ctx, "memory", None)
        if memory_layer is not None:
            return memory_layer.render()

        # Fallback: simple render from store
        if self._store is None:
            return ""

        active = self._store.get_active()
        if not active:
            return ""

        lines = ["<memory-context>"]
        for entry in list(active.values())[:5]:
            text = entry.content.summary or entry.content.text
            if len(text) > 200:
                text = text[:197] + "..."
            lines.append(f"- [{entry.type.value}] {text}")
        lines.append("</memory-context>")
        return "\n".join(lines)
