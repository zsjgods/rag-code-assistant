"""MemoryLayer — Context OS adapter for Memory OS.

This is the ONLY contact point between Memory OS and Context OS.
MemoryLayer extends BaseLayer, so Context OS sees it as just another context source.

Phase 2 (M7): MemoryPlanner → RetrievalEngine → Memory Context.
  Falls back to Phase 1 (importance × freshness top-N) when RetrievalEngine
  is not configured.
"""

from src.context.layers.base import BaseLayer
from src.memory.retrieval.planner import TaskContext
from src.memory.retrieval.query import RetrievalQuery
from src.memory.types import MemoryType


class MemoryLayer(BaseLayer):
    """Context OS layer that injects task-relevant memories into the system prompt.

    Phase 2 implementation:
      1. Build TaskContext from current conversation state
      2. Planner.plan(task_context) → RetrievalIntent
      3. RetrievalEngine.retrieve(intent) → ranked results
      4. Format as <memory-context> block

    Phase 1 fallback (no RetrievalEngine):
      Direct Store access, sorted by importance × freshness.

    Usage:
        layer = MemoryLayer(store=store, engine=retrieval_engine, max_entries=5)
        orch.register_layer(layer, position=1)
    """

    is_immutable = False
    name = "memory"

    def __init__(self, store, max_entries: int = 5, engine=None):
        """Initialize the memory layer.

        Args:
            store: MemoryStore instance.
            max_entries: Maximum memory entries to render.
            engine: RetrievalEngine (optional). If None, falls back to Phase 1.
        """
        self._store = store
        self._max_entries = max_entries
        self._engine = engine  # RetrievalEngine | None
        self._last_messages: list[str] = []  # Tracked for Planner context

    def render(self) -> str:
        """Render task-relevant memories as a <memory-context> block.

        Returns:
            Formatted <memory-context> XML block, or "" if no memories.
        """
        if self._engine is not None:
            return self._render_phase2()
        return self._render_phase1()

    def clear(self) -> None:
        self._last_messages.clear()

    def token_count(self) -> int:
        rendered = self.render()
        return len(rendered) // 4 if rendered else 0

    # ── Public API ──────────────────────────────────────────

    def set_engine(self, engine) -> None:
        """Upgrade from Phase 1 to Phase 2 at runtime."""
        self._engine = engine

    def track_message(self, text: str) -> None:
        """Track recent conversation messages for Planner context.

        Called by Agent Loop after each assistant response.
        """
        self._last_messages.append(text)
        # Keep only the last N
        max_recent = 10
        if len(self._last_messages) > max_recent:
            self._last_messages = self._last_messages[-max_recent:]

    # ═══════════════════════════════════════════════════════════
    # Phase 2: Planner → Retrieval → Context
    # ═══════════════════════════════════════════════════════════

    def _render_phase2(self) -> str:
        """M7 path: task-aware retrieval."""
        # Build task context from tracked state
        task_ctx = TaskContext(
            current_query=self._last_messages[-1] if self._last_messages else "",
            recent_messages=self._last_messages[-4:-1] if len(self._last_messages) > 1 else [],
            current_objective=self._get_objective(),
            active_files=self._get_active_files(),
        )

        # Planner → Retrieval
        results = self._engine.retrieve_for_task(task_ctx)
        if not results:
            return ""

        # Limit to max_entries
        results = results[:self._max_entries]

        # Group by type
        by_type: dict[MemoryType, list] = {}
        for r in results:
            entry = r.entry
            if entry is None:
                continue
            t = entry.type
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entry)

        if not by_type:
            return ""

        # Render
        lines = ["<memory-context>"]
        lines.append("The following is relevant knowledge from past experience:")
        lines.append("")

        for mtype in MemoryType:
            entries = by_type.get(mtype, [])
            if not entries:
                continue
            type_label = _TYPE_LABELS.get(mtype, mtype.value.title())
            lines.append(f"## {type_label}")
            for entry in entries:
                text = entry.content.summary or entry.content.text
                if len(text) > 300:
                    text = text[:297] + "..."
                lines.append(f"- {text}")
            lines.append("")

        lines.append("</memory-context>")
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # Phase 1: importance × freshness fallback
    # ═══════════════════════════════════════════════════════════

    def _render_phase1(self) -> str:
        """M6 fallback: direct store access, sorted by importance × freshness."""
        active = self._store.get_active()
        if not active:
            return ""

        scored = [(e.importance * e.freshness, e) for e in active.values()]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:self._max_entries]
        if not top:
            return ""

        by_type: dict[MemoryType, list] = {}
        for _, entry in top:
            t = entry.type
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entry)

        lines = ["<memory-context>"]
        lines.append("The following is relevant knowledge from past experience:")
        lines.append("")

        for mtype in MemoryType:
            entries = by_type.get(mtype, [])
            if not entries:
                continue
            type_label = _TYPE_LABELS.get(mtype, mtype.value.title())
            lines.append(f"## {type_label}")
            for entry in entries:
                text = entry.content.summary or entry.content.text
                if len(text) > 300:
                    text = text[:297] + "..."
                lines.append(f"- {text}")
            lines.append("")

        lines.append("</memory-context>")
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # Context helpers
    # ═══════════════════════════════════════════════════════════

    def _get_objective(self) -> str:
        """Read current objective from Store (accessed via the MemoryStore's events)."""
        try:
            # Store is not directly accessible here; fall back to empty
            return ""
        except Exception:
            return ""

    def _get_active_files(self) -> list[str]:
        """Get currently active files from workspace context."""
        # MemoryLayer doesn't have direct access to Context OS state.
        # The caller (agent loop) should call track_file() to feed this info.
        return self._tracked_files if hasattr(self, "_tracked_files") else []

    def track_files(self, files: list[str]) -> None:
        """Track currently open files (called by agent loop)."""
        self._tracked_files = files


# ── Type labels for rendering ──

_TYPE_LABELS: dict[MemoryType, str] = {
    MemoryType.USER: "👤 用户偏好",
    MemoryType.PROJECT: "📁 项目约定",
    MemoryType.CONVERSATION: "💬 对话结论",
    MemoryType.DECISION: "🎯 关键决策",
    MemoryType.EXPERIENCE: "💡 经验教训",
    MemoryType.TOOL: "🔧 工具经验",
    MemoryType.KNOWLEDGE: "📚 知识",
    MemoryType.CODE: "💻 代码模式",
}
