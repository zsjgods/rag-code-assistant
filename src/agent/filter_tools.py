"""Three-level tool isolation for sub-agents.

Layer 1: Global deny list — tools no sub-agent can ever use
Layer 2: Type-based whitelist — explore(只读) / background(受限) / full(全部)
Layer 3: Agent-defined allow/deny — per-agent custom overrides
"""

from src.tools.base import Tool

# Layer 1: Global deny — prevents recursion and authority confusion
GLOBAL_DENY = {
    "task",             # sub-agent can't spawn more sub-agents
    "TaskStop",         # sub-agent can't kill other tasks
    "AskUserQuestion",  # sub-agent can't ask user (background)
    "ExitPlanMode",     # sub-agent can't exit plan mode
    "plan_approval",    # sub-agent can't approve plans
    "shutdown_request", # sub-agent can't shutdown others
    "spawn_teammate",   # sub-agent can't spawn teammates
    "idle",             # sub-agent's idle is managed by lifecycle
}

# Layer 2: Type-based whitelists
EXPLORE_TOOLS = {"bash", "read_file", "grep", "glob", "task_list", "task_get", "load_skill", "compress"}

BACKGROUND_TOOLS = {
    "bash", "read_file", "write_file", "edit_file",
    "grep", "glob", "grep_search", "web_search",
}

FULL_TOOLS = set()  # Empty = all tools (minus global deny)


def filter_tools_for_agent(
    tools: dict[str, Tool],
    agent_type: str = "general-purpose",
    allowed: list[str] | None = None,
    disallowed: list[str] | None = None,
) -> dict[str, Tool]:
    """
    Three-layer tool filter for sub-agents.

    Returns a filtered dict of {name: Tool}.
    """
    # Layer 1: Remove globally denied tools
    filtered = {n: t for n, t in tools.items() if n not in GLOBAL_DENY}

    # Layer 2: Apply type-based whitelist
    if agent_type == "Explore":
        filtered = {n: t for n, t in filtered.items() if n in EXPLORE_TOOLS}
    elif agent_type == "background":
        filtered = {n: t for n, t in filtered.items() if n in BACKGROUND_TOOLS}
    # "general-purpose" — no layer-2 restriction

    # Layer 3: Agent-defined overrides
    if disallowed:
        filtered = {n: t for n, t in filtered.items() if n not in disallowed}
    if allowed and "*" not in allowed:
        filtered = {n: t for n, t in filtered.items() if n in allowed}

    return filtered


def get_agent_tool_restriction(agent_type: str) -> dict:
    """Return tool restriction metadata for an agent type."""
    restrictions = {
        "Explore": {
            "disallowedTools": ["Write", "Edit", "Bash"],
            "readOnly": True,
        },
        "general-purpose": {
            "allowedTools": ["*"],
            "readOnly": False,
        },
        "background": {
            "allowedTools": list(BACKGROUND_TOOLS),
            "readOnly": False,
        },
    }
    return restrictions.get(agent_type, restrictions["general-purpose"])
