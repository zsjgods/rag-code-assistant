"""Intent classification — routes user queries to tool subsets.

Two modes:
  keyword (default): 0 token, regex-based, fast
  llm: uses a lightweight model (Haiku) for more nuanced classification

Why intent matters:
  - Cost: don't send 50 tool schemas for a "hello" message
  - Accuracy: fewer tools = less chance of selecting the wrong one
  - Safety: destructive intents can be blocked before LLM sees them

Usage:
  classifier = IntentClassifier(mode="keyword")
  intent = classifier.classify("search for auth-related code")
  # -> "code_search"

  tools = filter_by_intent(registry, intent)
  # -> only grep, glob, rag_search, read_file
"""

import re
from collections import OrderedDict


# ── Intent -> allowed tool names ──────────────────────────────

DEFAULT_ROUTES: dict[str, list[str]] = {
    "code_search": [
        "grep", "glob", "memory_search", "read_file",
    ],
    "code_edit": [
        "read_file", "write_file", "edit_file", "bash",
    ],
    "code_index": [
        "memory_search", "grep", "glob", "read_file",
    ],
    "task_manage": [
        "task_create", "task_get", "task_update", "task_list",
        "TodoWrite", "set_objective",
    ],
    "web_search": [
        # MCP tools — dynamically added when MCP is connected
    ],
    "knowledge": [
        # No tools — direct answer from model knowledge
    ],
    "unsafe": [
        # Blocked — no LLM call at all
    ],
}

# Dynamic: tools that should always be available regardless of intent
ALWAYS_AVAILABLE = [
    "list_skills", "load_skill", "compress",
    "scratchpad_write", "scratchpad_read",
    "check_background",
]


# ── Keyword patterns per intent ─────────────────────────────

KEYWORD_PATTERNS: dict[str, list[str]] = {
    "code_search": [
        # "find all Python files" / "search for auth code"
        r"\b(search|find|grep|look|locate|scan|在哪|搜索|查找|找|搜)\b",
        # "where is X defined" / "which file has Y"
        r"\b(where|which|show me|read)\b.{0,30}\b(code|file|content|定义|实现|def |import|function|class|method)\b",
        # "list Python files" / "show test files"
        r"\b(list|show|get|display|read)\b.{0,20}\b(file|files|Python|\.py|\.md|source)\b",
    ],
    "code_edit": [
        # "fix the bug in main.py" / "edit config"
        r"\b(edit|modify|change|fix|refactor|rewrite|update|delete|remove|替换|修改|改|修复|重构|删)\b",
        # "create a file" / "write to file" / "add function"
        r"\b(create|write|add|make|save|put|创建|写|加|新增)\b.{0,20}\b(file|to |in |a |function|class|test)\b",
        # "run tests" / "execute pytest"
        r"\b(run|execute|跑|执行|运行)\b.{0,15}\b(test|pytest|command|python|npm|script|测试)\b",
    ],
    "code_index": [
        r"\b(build|create|rebuild|init)\b.{0,10}\b(index|索引|embedding|vector|searchable)\b",
        r"\b(search|find|look|query)\b.{0,20}\b(codebase|project|source|code|代码|项目)\b",
    ],
    "task_manage": [
        r"\b(tasks?|todos?|objective|goal|任务|待办|计划|目标)\b",
        r"\b(what|show|list|check|get)\b.{0,10}\b(left|remaining|pending|next|doing|status|progress|tasks?)\b",
        r"\b(set|update|mark|complete|finish|done)\b.{0,10}\b(task|objective|goal|status|任务|目标)\b",
    ],
    "unsafe": [
        r"\brm\s+-rf\s+/",
        r"\bsudo\s+rm\b",
        r"\bdelete\b.*\b(all|everything|entire|全部|所有|every)\b.*\b(file|data|disk|drive)\b",
    ],
}


class IntentClassifier:
    """Classify user queries into intent categories.

    Two modes:
      - "keyword": regex pattern matching (0 token, instant)
      - "llm": lightweight LLM classification (more accurate, ~50 tokens)
    """

    def __init__(self, mode: str = "keyword", routes: dict = None,
                 llm_call=None):
        self.mode = mode
        self.routes = routes or DEFAULT_ROUTES
        self._llm_call = llm_call

    def classify(self, query: str) -> str:
        """Classify a user query into an intent category.

        Returns one of: code_search, code_edit, code_index, task_manage,
                       web_search, knowledge, unsafe
        """
        if self.mode == "llm" and self._llm_call:
            return self._classify_llm(query)
        return self._classify_keyword(query)

    def _classify_keyword(self, query: str) -> str:
        """Keyword-based classification. 0 token cost."""
        query_lower = query.lower()

        # Check unsafe first — safety before everything
        for pattern in KEYWORD_PATTERNS.get("unsafe", []):
            if re.search(pattern, query, re.IGNORECASE):
                return "unsafe"

        # Check each intent in priority order
        # task_manage before code_edit: "update the task list" is task, not edit
        for intent in ["code_search", "task_manage", "code_edit", "code_index"]:
            for pattern in KEYWORD_PATTERNS.get(intent, []):
                if re.search(pattern, query, re.IGNORECASE):
                    return intent

        # Default: knowledge (no tools needed)
        return "knowledge"

    def _classify_llm(self, query: str) -> str:
        """Use a lightweight LLM to classify intent. ~50 tokens per call."""
        categories = "\n".join(
            f"  - {name}: {', '.join(tools) if tools else 'no tools, answer directly'}"
            for name, tools in self.routes.items()
        )

        prompt = (
            f"Classify this user message into ONE category. Output ONLY the category name.\n\n"
            f"Categories:\n{categories}\n\n"
            f"User message: \"{query}\"\n\n"
            f"Category:"
        )

        try:
            response = self._llm_call(prompt)
            result = response.strip().lower().replace(" ", "_")
            if result in self.routes:
                return result
            # Fallback: try partial match
            for intent in self.routes:
                if intent in result:
                    return intent
        except Exception:
            pass

        return "knowledge"


def filter_by_intent(registry, intent: str, routes: dict = None) -> list[dict]:
    """Filter a ToolRegistry to only include tools for the given intent.

    Args:
        registry: ToolRegistry instance
        intent: intent category string
        routes: optional custom routes dict

    Returns:
        list of tool dicts in Anthropic API format
    """
    routes = routes or DEFAULT_ROUTES

    allowed = set(routes.get(intent, []))
    allowed.update(ALWAYS_AVAILABLE)

    tools = registry.to_api_format()
    return [t for t in tools if t["name"] in allowed]


def get_tool_names_by_intent(intent: str, routes: dict = None) -> set[str]:
    """Get the set of tool names for a given intent."""
    routes = routes or DEFAULT_ROUTES
    allowed = set(routes.get(intent, []))
    allowed.update(ALWAYS_AVAILABLE)
    return allowed
