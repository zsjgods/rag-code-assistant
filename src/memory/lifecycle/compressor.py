"""MemoryCompressor — compress memory groups into summaries.

Three strategies:
  - RuleBasedCompression — no LLM: merge tags, truncate+join text
  - LLMCompression        — LLM generates summary (needs llm_call)
  - HybridCompression     — small groups → RuleBased, large → LLM

Original entries are archived (not deleted). Relations preserved via derived_from.
"""

import time
from abc import ABC, abstractmethod

from src.memory.events import MemoryEvent, MemoryEventBus, MemoryEventPayload
from src.memory.identity import MemoryID
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.policy import CompressionPolicy
from src.memory.types import MemoryEntry, MemoryType


# ═══════════════════════════════════════════════════════════════════
# Compression Strategies
# ═══════════════════════════════════════════════════════════════════

class CompressionStrategy(ABC):
    """Abstract compression strategy."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compress(self, group: list[MemoryEntry]) -> MemoryEntry:
        """Compress a group into one summary entry.

        Args:
            group: List of MemoryEntry to compress (all same type).

        Returns:
            A new MemoryEntry representing the compressed summary.
        """
        ...


class RuleBasedCompression(CompressionStrategy):
    """No LLM: truncate and join. Best for simple, factual memories."""

    name = "rule"

    def compress(self, group: list[MemoryEntry]) -> MemoryEntry:
        if not group:
            raise ValueError("Cannot compress empty group")

        # Use highest-importance entry as base
        base = max(group, key=lambda e: e.score.importance)

        # Merge all tags
        all_tags: set[str] = set()
        for e in group:
            all_tags.update(e.content.tags)

        # Join summaries
        summaries = [e.content.summary or e.content.text[:100] for e in group]
        merged_summary = "; ".join(summaries)
        if len(merged_summary) > 300:
            merged_summary = merged_summary[:297] + "..."

        # Join texts (truncated per entry)
        texts = []
        for e in group:
            t = e.content.text
            if len(t) > 500:
                t = t[:497] + "..."
            texts.append(t)
        merged_text = "\n\n---\n\n".join(texts)

        # Average importance
        avg_importance = sum(e.score.importance for e in group) / len(group)

        return MemoryEntry.create(
            text=merged_text,
            type=base.type,
            summary=f"[Compressed {len(group)}] {merged_summary}",
            tags=sorted(all_tags),
            importance=avg_importance,
            source="compression:rule",
            reason=f"Compressed from {len(group)} memories: {', '.join(e.id_str[:8]+'..' for e in group)}",
        )


class LLMCompression(CompressionStrategy):
    """LLM generates a concise summary. Needs llm_call."""

    name = "llm"

    def __init__(self, llm_call=None, prompt_loader=None):
        self._llm_call = llm_call or (lambda x: "")
        self._prompts = prompt_loader

    def compress(self, group: list[MemoryEntry]) -> MemoryEntry:
        if not group:
            raise ValueError("Cannot compress empty group")

        base = max(group, key=lambda e: e.score.importance)
        all_tags: set[str] = set()
        context_parts = []
        for i, e in enumerate(group):
            all_tags.update(e.content.tags)
            context_parts.append(f"[{i+1}] Type: {e.type.value}\nSummary: {e.content.summary}\nContent: {e.content.text[:400]}")

        context = "\n\n".join(context_parts)

        # Try to use PromptLoader if available
        prompt = f"Compress the following {len(group)} memories into ONE concise summary memory. Preserve ALL key facts.\n\n{context}\n\nOutput JSON: {{\"summary\": \"...\", \"text\": \"...\", \"tags\": [...]}}"
        if self._prompts:
            try:
                prompt = self._prompts.load("compress_user", group_context=context, count=str(len(group)))
            except Exception:
                pass

        try:
            response = self._llm_call(prompt)
            # Parse JSON from LLM response
            import json
            import re
            md = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
            if md:
                data = json.loads(md.group(1).strip())
            else:
                data = json.loads(response)

            summary = data.get("summary", f"Compressed {len(group)} memories")
            text = data.get("text", context[:1000])
            tags = data.get("tags", list(all_tags))
        except Exception:
            # Fallback to rule-based on LLM failure
            summary = f"[Compressed {len(group)}] " + (base.content.summary or base.content.text[:80])
            text = context[:2000]
            tags = sorted(all_tags)

        avg_importance = sum(e.score.importance for e in group) / len(group)

        return MemoryEntry.create(
            text=text,
            type=base.type,
            summary=summary,
            tags=tags,
            importance=avg_importance,
            source="compression:llm",
            reason=f"LLM-compressed from {len(group)} memories",
        )


class HybridCompression(CompressionStrategy):
    """Small groups (≤3) → RuleBased, large (>3) → LLM."""

    name = "hybrid"

    def __init__(self, llm_call=None, prompt_loader=None):
        self._rule = RuleBasedCompression()
        self._llm = LLMCompression(llm_call=llm_call, prompt_loader=prompt_loader)

    def compress(self, group: list[MemoryEntry]) -> MemoryEntry:
        if len(group) <= 3:
            return self._rule.compress(group)
        return self._llm.compress(group)


# ═══════════════════════════════════════════════════════════════════
# MemoryCompressor
# ═══════════════════════════════════════════════════════════════════

class MemoryCompressor:
    """Find compressible groups and compress them.

    Usage:
        compressor = MemoryCompressor(store, events, vector_index, embedder, llm_call, config)
        results = compressor.schedule()  # Find and compress groups
    """

    def __init__(
        self,
        store,                  # MemoryStore
        events: MemoryEventBus,
        vector_index=None,      # BaseVectorIndex (M7) for similarity search
        embedder=None,          # DenseEmbedder
        llm_call=None,
        prompt_loader=None,
        config: LifecycleConfig | None = None,
    ):
        self._store = store
        self._events = events
        self._vector_index = vector_index
        self._embedder = embedder
        self._config = config or LifecycleConfig()
        self._policy = CompressionPolicy(self._config)

        # Select strategy
        strategy_name = self._config.compression_strategy
        if strategy_name == "llm":
            self._strategy: CompressionStrategy = LLMCompression(llm_call, prompt_loader)
        elif strategy_name == "hybrid":
            self._strategy: CompressionStrategy = HybridCompression(llm_call, prompt_loader)
        else:
            self._strategy: CompressionStrategy = RuleBasedCompression()

    def schedule(self) -> list[str]:
        """Find and compress groups. Returns list of new compressed entry IDs."""
        if not self._policy._cfg.compression_enabled:
            return []

        groups = self._find_compressible_groups()
        if not groups:
            return []

        compressed_ids: list[str] = []
        for group in groups:
            should, reason = self._policy.should_compress(group)
            if not should:
                continue

            try:
                new_id = self._compress_group(group)
                if new_id:
                    compressed_ids.append(new_id)
            except Exception:
                pass

        return compressed_ids

    def _find_compressible_groups(self) -> list[list[MemoryEntry]]:
        """Find groups of similar memories for compression."""
        active = self._store.get_active()
        if len(active) < self._config.compression_min_group_size:
            return []

        # Group by type
        by_type: dict[MemoryType, list[MemoryEntry]] = {}
        for entry in active.values():
            t = entry.type
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entry)

        groups: list[list[MemoryEntry]] = []
        for entries in by_type.values():
            if len(entries) < self._config.compression_min_group_size:
                continue
            # Simple grouping: all same-type entries become one group
            # Future: use vector_index for semantic subgrouping
            groups.append(entries[:self._config.compression_max_group_size])

        return groups

    def _compress_group(self, group: list[MemoryEntry]) -> str | None:
        """Compress one group. Returns new entry ID or None."""
        if len(group) < 2:
            return None

        now = time.time()

        # Create compressed summary entry
        summary_entry = self._strategy.compress(group)
        new_id = self._store.create(summary_entry)

        # Add derived_from relations
        for original in group:
            from src.memory.intelligence.relation_types import RelationType, apply_relation_pair
            apply_relation_pair(summary_entry, original, RelationType.DERIVED_FROM)

            # Archive original
            self._store.archive(original.id)

        # Emit COMPRESSED
        self._events.emit(MemoryEventPayload(
            event=MemoryEvent.COMPRESSED,
            entry_id=new_id.value,
            timestamp=now,
            triggered_by="compressor",
            metadata={
                "group_size": len(group),
                "original_ids": [e.id_str for e in group],
                "strategy": self._strategy.name,
            },
        ))

        return new_id.value

    def stats(self) -> dict:
        return {
            "enabled": self._config.compression_enabled,
            "strategy": self._strategy.name,
            "min_group_size": self._config.compression_min_group_size,
        }
