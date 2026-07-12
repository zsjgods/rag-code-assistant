"""Built-in Collectors for the Context Selection Pipeline.

Each Collector maps to a Layer and extracts Candidates.
Collectors are read-only — they never modify Layer data.
"""

import time as time_module

from src.context.selection.candidate import Candidate
from src.context.selection.collector import Collector, SelectionContext


# ── InstructionCollector ────────────────────────────────────────────────


class InstructionCollector(Collector):
    """Single candidate — the full instruction (system prompt).

    Always priority 0 (reserved). Single item_id="system".
    """

    source_name = "instruction"

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        if ctx.instruction is None:
            return []
        content = ctx.instruction.render()
        tokens = ctx.instruction.token_count()
        return [
            Candidate(
                layer_name=self.source_name,
                item_id="system",
                token_count=tokens,
                recency=time_module.time(),
                importance=1.0,
            )
        ]

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> str:
        if ctx.instruction is None:
            return ""
        return ctx.instruction.render()


# ── WorkspaceCollector ─────────────────────────────────────────────────


class WorkspaceCollector(Collector):
    """Single candidate — the workspace state block."""

    source_name = "workspace"

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        if ctx.workspace is None:
            return []
        tokens = ctx.workspace.token_count()
        return [
            Candidate(
                layer_name=self.source_name,
                item_id="state",
                token_count=tokens,
                recency=time_module.time(),
                importance=0.6,
            )
        ]

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> str:
        if ctx.workspace is None:
            return ""
        return ctx.workspace.render()


# ── SummaryCollector ────────────────────────────────────────────────────


class SummaryCollector(Collector):
    """Single candidate — the latest rolling summary.

    If SummaryLayer has no entries, returns empty list.
    """

    source_name = "summary"

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        if ctx.summary is None:
            return []
        latest = ctx.summary.get_latest()
        if latest is None:
            return []
        return [
            Candidate(
                layer_name=self.source_name,
                item_id=f"v{latest.version}",
                token_count=latest.token_count,
                recency=latest.last_used_at or latest.created_at,
                importance=latest.importance,
                metadata={
                    "version": latest.version,
                    "source": latest.source,
                },
            )
        ]

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> list[dict]:
        if ctx.summary is None:
            return []
        return ctx.summary.render()


# ── FileCacheCollector ─────────────────────────────────────────────────


class FileCacheCollector(Collector):
    """One candidate per cached file, ordered by last_access (most recent first)."""

    source_name = "file_cache"

    def __init__(self, max_candidates: int = 10):
        self._max_candidates = max_candidates

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        if ctx.file_cache is None:
            return []
        candidates: list[Candidate] = []
        for path in ctx.file_cache.cached_paths:
            info = ctx.file_cache.get_info(path)
            if info is None:
                continue
            candidates.append(
                Candidate(
                    layer_name=self.source_name,
                    item_id=path,
                    token_count=len(info.content) // 4,
                    recency=info.last_access,
                    importance=0.4,
                    metadata={"path": path, "truncated": info.is_truncated},
                )
            )
            if len(candidates) >= self._max_candidates:
                break
        return candidates

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> str:
        if ctx.file_cache is None:
            return ""
        content = ctx.file_cache.get(candidate.item_id)
        return content or ""


# ── ConversationCollector ──────────────────────────────────────────────


class ConversationCollector(Collector):
    """One candidate per round-trip, ordered by recency (newest first).

    A round-trip starts with an assistant message and includes all subsequent
    tool_results until the next assistant message. If there's an unpaired
    user message at the end, it's included as a partial round-trip.

    Also produces a single "head" candidate for messages before the first
    assistant message (system-prompt-era user messages).
    """

    source_name = "conversation"

    def __init__(self, max_rounds: int = 20):
        self._max_rounds = max_rounds

    @staticmethod
    def _group_by_roundtrip(messages: list[dict]) -> list[list[dict]]:
        """Group messages into round-trips.

        Each round-trip starts with an assistant message and includes
        all subsequent user/tool messages until the next assistant.
        Messages before the first assistant are a "head" group.
        """
        groups: list[list[dict]] = []
        current: list[dict] = []

        for msg in messages:
            if msg["role"] == "assistant" and current:
                # Assistant message signals a new round-trip
                # Current group is complete
                groups.append(current)
                current = []
            current.append(msg)

        if current:
            groups.append(current)

        return groups

    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        if ctx.conversation is None:
            return []

        from src.compression.micro import estimate_tokens

        messages = ctx.conversation.get_messages()
        groups = self._group_by_roundtrip(messages)

        # Head group (before first assistant) — low importance
        candidates: list[Candidate] = []
        for i, group in enumerate(groups):
            tokens = estimate_tokens(group)
            is_recent = i >= len(groups) - self._max_rounds
            if not is_recent:
                # Beyond our window — skip old rounds entirely
                continue

            candidates.append(
                Candidate(
                    layer_name=self.source_name,
                    item_id=f"round_{i:04d}",
                    token_count=tokens,
                    recency=time_module.time() - (len(groups) - i) * 10,
                    importance=0.3 if i == 0 else 0.7,
                    metadata={"round_index": i},
                )
            )

        # Return most recent first
        candidates.reverse()
        return candidates

    @staticmethod
    def _resolve_round(ctx: SelectionContext, round_index: int) -> list[dict]:
        """Get messages for a specific round-trip from the conversation."""
        if ctx.conversation is None:
            return []
        messages = ctx.conversation.get_messages()
        groups = ConversationCollector._group_by_roundtrip(messages)
        if 0 <= round_index < len(groups):
            return groups[round_index]
        return []

    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> list[dict]:
        round_index = candidate.metadata.get("round_index", -1)
        return self._resolve_round(ctx, round_index)


