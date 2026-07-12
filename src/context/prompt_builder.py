"""PromptBuilder — single exit point for prompt assembly.

Iterates over registered layers, renders each, and assembles the final
(system, messages) pair sent to the LLM.

Assembly logic:
  - The first layer that renders to str becomes the system prompt
  - All layers that render to list[dict] are concatenated into messages
  - Future layers (scratchpad, summary) can inject into either position
"""

from src.context.layers.base import BaseLayer
from src.context.types import BuildResult, LayerStats


class PromptBuilder:
    """Assembles layers into the final prompt for each agent loop iteration.

    This is the SINGLE EXIT POINT for prompt construction. No other module
    should assemble system + messages directly.

    Assembly order = layer registration order:
      InstructionLayer (str)     → system prompt
      ConversationLayer (list)   → messages
      Future layers can slot in at any position via register_layer(position=N)
    """

    def __init__(
        self,
        layers: list[BaseLayer] | None = None,
        total_budget: int = 180000,
    ):
        self._layers: list[BaseLayer] = layers or []
        self.total_budget = total_budget

    # ── Layer management ────────────────────────────────

    def add_layer(self, layer: BaseLayer, position: int | None = None) -> None:
        """Register a layer at the specified position (or end if None)."""
        if position is not None:
            self._layers.insert(position, layer)
        else:
            self._layers.append(layer)

    def remove_layer(self, name: str) -> bool:
        """Remove a layer by name. Returns True if found and removed."""
        for i, layer in enumerate(self._layers):
            if layer.name == name:
                self._layers.pop(i)
                return True
        return False

    def get_layer(self, name: str) -> BaseLayer | None:
        """Find a layer by name."""
        for layer in self._layers:
            if layer.name == name:
                return layer
        return None

    def iter_layers(self) -> list[BaseLayer]:
        """Return all registered layers in assembly order."""
        return list(self._layers)

    # ── Build ───────────────────────────────────────────

    def build(self) -> BuildResult:
        """Assemble the final prompt from all registered layers.

        For each layer:
          - str content  → appended to system prompt parts
          - list content → extended into messages list

        The first str layer's content is the main system prompt.
        Multiple str layers are joined with newlines.

        Returns:
            BuildResult with .system, .messages, and per-layer .stats
        """
        system_parts: list[str] = []
        message_parts: list[list[dict]] = []
        stats: list[LayerStats] = []

        for layer in self._layers:
            content = layer.render()
            tokens = layer.token_count()

            stat = LayerStats(
                layer_name=layer.name,
                token_count=tokens,
                budget_used=tokens / self.total_budget if self.total_budget > 0 else 0.0,
                is_over_budget=False,
            )

            if isinstance(content, str):
                if content:  # Skip empty strings
                    system_parts.append(content)
                # Flag if system prompt exceeds ~30% of budget
                system_tokens = sum(len(s) for s in system_parts) // 4
                stat.is_over_budget = system_tokens > int(self.total_budget * 0.30)
            elif isinstance(content, list):
                message_parts.append(content)
                # Flag if conversation exceeds its budget fraction
                conv_tokens = sum(len(str(m)) for m in content) // 4
                stat.is_over_budget = conv_tokens > int(self.total_budget * 0.90)

            stats.append(stat)

        # Assemble
        system = "\n".join(system_parts)
        messages: list[dict] = []
        for part in message_parts:
            messages.extend(part)

        return BuildResult(system=system, messages=messages, stats=stats)

    # ── M4: Build from Package ─────────────────────────

    def build_from_package(self, package: "PromptPackage") -> BuildResult:
        """Build the final prompt from a pre-assembled PromptPackage.

        This is the M4+ path. The PromptBuilder becomes a pure assembler:
          - system_parts are joined with newlines
          - message_parts are flattened into a single messages list

        Args:
            package: A PromptPackage produced by the SelectionPipeline.

        Returns:
            BuildResult compatible with the agent_loop.
        """
        from src.context.types import LayerStats

        system = "\n".join(package.system_parts)
        messages: list[dict] = []
        for part in package.message_parts:
            messages.extend(part)

        stats = [
            LayerStats(layer_name=k, token_count=v)
            for k, v in package.token_usage.items()
        ]

        return BuildResult(system=system, messages=messages, stats=stats)

    def estimate_total_tokens(self) -> int:
        """Estimate total tokens across all layers."""
        return sum(layer.token_count() for layer in self._layers)

    def get_layer_stats(self) -> list[LayerStats]:
        """Get per-layer stats without a full build."""
        stats: list[LayerStats] = []
        for layer in self._layers:
            tokens = layer.token_count()
            stats.append(
                LayerStats(
                    layer_name=layer.name,
                    token_count=tokens,
                    budget_used=tokens / self.total_budget
                    if self.total_budget > 0
                    else 0.0,
                )
            )
        return stats
