"""MemoryPlanner — task-aware memory retrieval planning.

Independent module. Does NOT import MemoryStore, Policy, or Pipeline.
Only generates RetrievalIntent from TaskContext — the actual retrieval
is delegated to RetrievalEngine.

Phase 1 implementation: rule-based intent generation (heuristics).
Future: LLM-based planning for more sophisticated intent extraction.
"""

from dataclasses import dataclass, field

from src.memory.types import MemoryType


# ═══════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TaskContext:
    """Current task context for planning memory retrieval.

    Populated by MemoryLayer.render() from Context OS state.
    """

    current_query: str = ""  # Latest user message
    recent_messages: list[str] = field(default_factory=list)  # Last N assistant responses
    current_objective: str = ""  # Persistent objective from Store
    active_files: list[str] = field(default_factory=list)  # Currently open files


@dataclass
class RetrievalIntent:
    """Output of MemoryPlanner — what to retrieve and how.

    This is a structured query intent, NOT the final result.
    RetrievalEngine converts it to a RetrievalQuery and executes.
    """

    query_text: str  # Search query text
    type_filter: list[str] | None = None  # MemoryType values
    tag_filter: list[str] | None = None
    project_filter: str | None = None
    min_importance: float = 0.0
    max_results: int = 10
    channel_weights: dict[str, float] | None = None  # Override default fusion weights


# ═══════════════════════════════════════════════════════════════════
# MemoryPlanner
# ═══════════════════════════════════════════════════════════════════

class MemoryPlanner:
    """Task-aware memory retrieval planner.

    Analyzes the current task context and generates a RetrievalIntent.
    Phase 1 uses rule-based heuristics. Phase 2+ can use LLM for more
    sophisticated intent extraction.

    Usage:
        planner = MemoryPlanner()
        intent = planner.plan(TaskContext(
            current_query="implement user authentication",
            current_objective="build a login system",
        ))
        # → RetrievalIntent(query_text="user authentication login",
        #                   type_filter=["decision","code","experience"])
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def plan(self, task_context: TaskContext) -> RetrievalIntent:
        """Generate a retrieval intent from task context.

        Phase 1 heuristics:
          1. Build query from current_query + objective
          2. Infer type filter from keyword patterns
          3. Infer tag filter from context clues (files, objective keywords)
        """
        if not self._enabled:
            # Degraded mode: just use current query text as-is
            return RetrievalIntent(
                query_text=task_context.current_query,
                max_results=10,
            )

        # Build query text
        query_parts = [task_context.current_query]
        if task_context.current_objective:
            # Add objective keywords (first 5 words)
            obj_words = task_context.current_objective.split()[:5]
            query_parts.append(" ".join(obj_words))
        query_text = " ".join(filter(None, query_parts))

        # Infer type filter
        type_filter = self._infer_types(task_context)

        # Infer tags
        tag_filter = self._infer_tags(task_context)

        return RetrievalIntent(
            query_text=query_text,
            type_filter=type_filter,
            tag_filter=tag_filter,
            max_results=10,
        )

    # ═══════════════════════════════════════════════════════════
    # Heuristics
    # ═══════════════════════════════════════════════════════════

    # Keywords → MemoryType mapping
    _TYPE_KEYWORDS: dict[str, list[str]] = {
        "user": ["user", "用户", "preference", "偏好", "profile"],
        "project": ["project", "项目", "convention", "约定", "setup", "structure", "架构"],
        "decision": ["decision", "决策", "decide", "选择", "tradeoff", "ADR", "architecture decision"],
        "experience": ["experience", "经验", "lesson", "教训", "pitfall", "踩坑", "bug", "error", "失败"],
        "tool": ["tool", "工具", "pytest", "docker", "git", "CI", "deploy", "build"],
        "knowledge": ["knowledge", "知识", "concept", "概念", "pattern", "模式"],
        "code": ["code", "代码", "pattern", "snippet", "implement", "实现", "refactor", "重构", "function", "class"],
    }

    def _infer_types(self, ctx: TaskContext) -> list[str] | None:
        """Infer which MemoryTypes are relevant based on query keywords."""
        text = (ctx.current_query + " " + ctx.current_objective).lower()
        matched_types: set[str] = set()

        for mem_type, keywords in self._TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    matched_types.add(mem_type)
                    break

        # If no specific pattern matched, return None (search all types)
        return list(matched_types) if matched_types else None

    def _infer_tags(self, ctx: TaskContext) -> list[str] | None:
        """Infer tags from context clues."""
        tags: list[str] = []

        # Extract from active files
        for file_path in ctx.active_files:
            # File extension → tag
            if file_path.endswith(".py"):
                tags.append("python")
            elif file_path.endswith(".ts") or file_path.endswith(".js"):
                tags.append("typescript" if file_path.endswith(".ts") else "javascript")
            elif file_path.endswith(".rs"):
                tags.append("rust")
            # Directory clues
            if "test" in file_path.lower():
                tags.append("testing")
            if "auth" in file_path.lower():
                tags.append("authentication")

        # Extract from objective
        objective_lower = ctx.current_objective.lower()
        objective_tags = {
            "auth": "authentication",
            "login": "authentication",
            "database": "database",
            "api": "api",
            "test": "testing",
            "deploy": "deployment",
            "docker": "docker",
            "refactor": "refactoring",
        }
        for keyword, tag in objective_tags.items():
            if keyword in objective_lower:
                tags.append(tag)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique if unique else None
