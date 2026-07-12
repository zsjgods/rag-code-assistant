"""Configuration loader — layered settings with priority merging.

Load order: settings.json (default) → settings.local.json (override)

Priority: local > project > default
"""

import json
from pathlib import Path


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. override values win."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(
    workdir: Path | None = None,
    config_name: str = "settings.json",
    local_name: str = "settings.local.json",
) -> dict:
    """Load and merge configuration from project directory.

    Returns merged config dict. local overrides project overrides defaults.
    """
    wd = workdir or Path.cwd()

    config = {}

    # Layer 1: Default settings
    default_path = wd / config_name
    if default_path.exists():
        try:
            config = json.loads(default_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Layer 2: Local overrides (gitignored, personal)
    local_path = wd / local_name
    if local_path.exists():
        try:
            local = json.loads(local_path.read_text(encoding="utf-8"))
            config = _deep_merge(config, local)
        except json.JSONDecodeError:
            pass

    return config


def get_agent_config(config: dict, agent_type: str) -> dict:
    """Get config for a specific agent type from the merged config."""
    agents = config.get("agents", {})
    return agents.get(agent_type, {})
