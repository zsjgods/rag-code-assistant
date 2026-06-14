"""Tool base interface — the contract every tool must fulfill."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Tool:
    """A tool the agent can invoke. Mirrors Claude Code's Tool interface."""

    name: str
    description: str
    input_schema: dict
    handler: Callable[..., str]

    # Safety flags — all default to fail-closed (unsafe)
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    is_destructive: bool = False

    # Lifecycle
    is_enabled: bool = True
    always_load: bool = False

    def execute(self, **kwargs) -> str:
        """Execute the tool with given arguments."""
        if not self.is_enabled:
            return f"Error: Tool '{self.name}' is disabled"
        try:
            return self.handler(**kwargs)
        except Exception as e:
            return f"Error executing '{self.name}': {e}"

    def to_api_format(self) -> dict:
        """Convert to Anthropic API tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def build_tool(
    name: str,
    description: str,
    input_schema: dict,
    handler: Callable[..., str],
    *,
    is_read_only: bool = False,
    is_concurrency_safe: bool = False,
    is_destructive: bool = False,
    always_load: bool = False,
) -> Tool:
    """Builder function — defaults to fail-closed on safety flags."""
    return Tool(
        name=name,
        description=description,
        input_schema=input_schema,
        handler=handler,
        is_read_only=is_read_only,
        is_concurrency_safe=is_concurrency_safe,
        is_destructive=is_destructive,
        always_load=always_load,
    )
