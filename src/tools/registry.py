"""Tool registry — central dispatch for all tools."""

from typing import Dict, List

from src.tools.base import Tool


class ToolRegistry:
    """Manages tool registration, lookup, and API-format export."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: List[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def remove_many(self, names: List[str]) -> None:
        for n in names:
            self.remove(n)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def to_api_format(self, include_disabled: bool = False) -> List[dict]:
        """Export tools in Anthropic API tool format."""
        tools = self._tools.values()
        if not include_disabled:
            tools = [t for t in tools if t.is_enabled]
        return [t.to_api_format() for t in tools]

    def execute(self, name: str, **kwargs) -> str:
        """Execute a tool by name. Returns error string if unknown."""
        tool = self.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        return tool.execute(**kwargs)


# Global singleton
registry = ToolRegistry()
