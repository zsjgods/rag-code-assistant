"""InstructionLayer — immutable system prompt container.

Holds all instruction-level content that must survive compression unchanged.

Structure (matches _build_system_prompt output exactly):
  1. <persistent-context> block (dynamic, refreshed from callbacks each render)
  2. base_system (static, set at construction)
  3. tool_rules (static)
  4. safety_rules (static)
  5. output_rules (static)
  6. Available skills block (static)
  7. Dynamic policies (runtime-added via add_policy)
"""

from typing import Callable

from src.context.layers.base import BaseLayer


class InstructionLayer(BaseLayer):
    """Immutable instruction layer — always at top of prompt, never compressed.

    Renders to a single system prompt string. The render() output is designed
    to be character-for-character identical to _build_system_prompt() in
    src/agent/loop.py when given the same inputs.
    """

    is_immutable = True

    def __init__(
        self,
        base_system: str = "",
        skills_descriptions: str = "",
        tool_rules: str = "",
        safety_rules: str = "",
        output_rules: str = "",
        get_objective: "Callable[[], str] | None" = None,
        get_persistent: "Callable[[], list[str]] | None" = None,
    ):
        # ── Static parts (never change after construction) ──
        self._base_system = base_system
        self._skills = skills_descriptions
        self._tool_rules = tool_rules
        self._safety_rules = safety_rules
        self._output_rules = output_rules

        # ── Dynamic callbacks (refreshed each render) ──
        self._get_objective = get_objective
        self._get_persistent = get_persistent

        # ── Runtime policies (added via add_policy) ──
        self._dynamic_policies: list[str] = []

    @property
    def name(self) -> str:
        return "instruction"

    def render(self) -> str:
        """Assemble the system prompt string.

        Mirrors _build_system_prompt() logic exactly:
          1. Start with base_system
          2. If persistent items exist, insert <persistent-context> block at front
          3. Append skills if present
          4. Append additional_context if present (not used in M1)
          5. Append dynamic policies

        Returns:
            Complete system prompt string.
        """
        parts: list[str] = []

        # ── Base system prompt (always first logical element) ──
        if self._base_system:
            parts.append(self._base_system)

        # ── Persistent context block (compression-immune) ──
        # Inserted at position 0 to match _build_system_prompt behavior
        persistent_items: list[str] = []

        if self._get_objective:
            obj = self._get_objective()
            if obj:
                persistent_items.append(f"CURRENT OBJECTIVE: {obj}")

        if self._get_persistent:
            facts = self._get_persistent()
            if facts:
                persistent_items.extend(facts)

        if persistent_items:
            block = (
                "<persistent-context>\n"
                + "\n".join(persistent_items)
                + "\n</persistent-context>"
            )
            parts.insert(0, block)

        # ── Static rule sections ──
        if self._tool_rules:
            parts.append(self._tool_rules)

        if self._safety_rules:
            parts.append(self._safety_rules)

        if self._output_rules:
            parts.append(self._output_rules)

        # ── Skills ──
        if self._skills:
            parts.append(f"\nAvailable skills:\n{self._skills}")

        # ── Dynamic policies (runtime-added, M1+ feature) ──
        for policy in self._dynamic_policies:
            parts.append(policy)

        return "\n".join(parts) if parts else ""

    # ── Mutation methods ────────────────────────────────

    def add_policy(self, text: str) -> None:
        """Add a runtime policy rule. Survives until clear()."""
        self._dynamic_policies.append(text)

    def set_objective_callback(self, fn: "Callable[[], str]") -> None:
        """Replace the objective callback."""
        self._get_objective = fn

    def set_persistent_callback(self, fn: "Callable[[], list[str]]") -> None:
        """Replace the persistent facts callback."""
        self._get_persistent = fn

    def clear(self) -> None:
        """Clear only dynamic policies. Static parts are preserved."""
        self._dynamic_policies.clear()
