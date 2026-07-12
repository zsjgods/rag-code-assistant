"""Memory Registry — unified registration center for Memory OS.

Registers:
  - MemoryType definitions (8 built-in types + plugins)
  - MemoryPlugin (external extensions)

The Registry is the single source of truth for "what MemoryTypes exist" and
"what are their default behaviors." Pipeline, Policy, and Tools query the
Registry rather than hardcoding type lists.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.memory.types import MemoryScope, MemoryType, MemoryVisibility


# ═══════════════════════════════════════════════════════════════════
# MemoryTypeDefinition
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemoryTypeDefinition:
    """Defines a registered MemoryType — its metadata and defaults."""
    name: str                            # Must match a MemoryType value
    description: str                     # Human-readable description
    default_scope: MemoryScope = MemoryScope.PROJECT
    default_visibility: MemoryVisibility = MemoryVisibility.PRIVATE
    required_fields: list[str] = field(default_factory=list)   # e.g. ["content.text"]
    optional_fields: list[str] = field(default_factory=lambda: [
        "content.summary", "content.tags", "content.source",
        "content.reason", "score.importance", "score.confidence",
    ])
    icon: str = "📝"                     # UI hint (CLI, dashboard, etc.)


# ═══════════════════════════════════════════════════════════════════
# Built-in type definitions
# ═══════════════════════════════════════════════════════════════════

BUILTIN_TYPES: list[MemoryTypeDefinition] = [
    MemoryTypeDefinition(
        name="user",
        description="User preferences, habits, and personal context",
        default_scope=MemoryScope.GLOBAL,
        default_visibility=MemoryVisibility.PRIVATE,
        required_fields=["content.text"],
        icon="👤",
    ),
    MemoryTypeDefinition(
        name="project",
        description="Project conventions, structure, and setup",
        default_scope=MemoryScope.PROJECT,
        default_visibility=MemoryVisibility.TEAM,
        required_fields=["content.text"],
        icon="📁",
    ),
    MemoryTypeDefinition(
        name="conversation",
        description="Key conclusions and context from conversations",
        default_scope=MemoryScope.SESSION,
        default_visibility=MemoryVisibility.PRIVATE,
        required_fields=["content.text"],
        icon="💬",
    ),
    MemoryTypeDefinition(
        name="decision",
        description="Architecture decisions, technical choices, trade-offs",
        default_scope=MemoryScope.PROJECT,
        default_visibility=MemoryVisibility.TEAM,
        required_fields=["content.text"],
        icon="🎯",
    ),
    MemoryTypeDefinition(
        name="experience",
        description="Lessons learned, pitfalls, successes, failures",
        default_scope=MemoryScope.PROJECT,
        default_visibility=MemoryVisibility.TEAM,
        required_fields=["content.text"],
        icon="💡",
    ),
    MemoryTypeDefinition(
        name="tool",
        description="Tool usage patterns, workarounds, best practices",
        default_scope=MemoryScope.GLOBAL,
        default_visibility=MemoryVisibility.PUBLIC,
        required_fields=["content.text"],
        icon="🔧",
    ),
    MemoryTypeDefinition(
        name="knowledge",
        description="General domain knowledge, facts, references",
        default_scope=MemoryScope.GLOBAL,
        default_visibility=MemoryVisibility.PUBLIC,
        required_fields=["content.text"],
        icon="📚",
    ),
    MemoryTypeDefinition(
        name="code",
        description="Code patterns, snippets, best practices, anti-patterns",
        default_scope=MemoryScope.PROJECT,
        default_visibility=MemoryVisibility.TEAM,
        required_fields=["content.text"],
        icon="💻",
    ),
]


# ═══════════════════════════════════════════════════════════════════
# MemoryPlugin ABC
# ═══════════════════════════════════════════════════════════════════

class MemoryPlugin(ABC):
    """External plugin interface.

    Plugins can:
      - Register custom MemoryTypes (e.g. "compliance", "security_audit")
      - Provide custom Pipeline stages
      - Provide custom Policy rules
      - Listen to events

    Plugins are discovered and loaded at MemoryCore initialization time.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name."""
        ...

    @abstractmethod
    def get_types(self) -> list[MemoryTypeDefinition]:
        """Return MemoryType definitions this plugin provides."""
        ...

    def get_pipeline_stages(self) -> list:
        """Optional: custom PipelineStage instances."""
        return []

    def get_policy_rules(self) -> list:
        """Optional: custom PolicyRule instances."""
        return []


# ═══════════════════════════════════════════════════════════════════
# MemoryRegistry
# ═══════════════════════════════════════════════════════════════════

class MemoryRegistry:
    """Unified registration center for Memory OS.

    Usage:
        registry = MemoryRegistry()
        registry.register_type(MemoryTypeDefinition(name="custom", ...))
        registry.register_plugin(MyPlugin())
        info = registry.get_type("user")  # → MemoryTypeDefinition
    """

    def __init__(self):
        self._types: dict[str, MemoryTypeDefinition] = {}
        self._plugins: dict[str, MemoryPlugin] = {}
        self._type_providers: dict[str, str] = {}  # type_name → plugin_name

        # Register built-in types
        for td in BUILTIN_TYPES:
            self.register_type(td, source="builtin")

    # ── Type Registry ──────────────────────────────────────────

    def register_type(
        self,
        type_def: MemoryTypeDefinition,
        source: str = "unknown",
    ) -> None:
        """Register a MemoryType definition. Replaces existing definition if any.

        Args:
            type_def: The type definition to register.
            source: Where this type came from ("builtin", plugin name, "user").
        """
        name = type_def.name
        self._types[name] = type_def
        if source != "builtin":
            self._type_providers[name] = source

    def unregister_type(self, name: str) -> bool:
        """Remove a registered type. Cannot remove built-in types."""
        if name in self._type_providers.get(name, "") == "builtin":
            return False  # Built-in types are permanent
        self._type_providers.pop(name, None)
        return self._types.pop(name, None) is not None

    def get_type(self, name: str) -> MemoryTypeDefinition | None:
        """Look up a type definition by name."""
        return self._types.get(name)

    def list_types(self) -> list[str]:
        """List all registered type names."""
        return list(self._types.keys())

    def list_type_definitions(self) -> list[MemoryTypeDefinition]:
        """List all registered type definitions."""
        return list(self._types.values())

    # ── Plugin Registry ────────────────────────────────────────

    def register_plugin(self, plugin: MemoryPlugin) -> None:
        """Register a plugin and its custom MemoryTypes."""
        # Remove existing plugin with same name
        self.unregister_plugin(plugin.name)

        self._plugins[plugin.name] = plugin
        for td in plugin.get_types():
            self.register_type(td, source=plugin.name)

    def unregister_plugin(self, name: str) -> bool:
        """Remove a plugin and all its registered types."""
        if name not in self._plugins:
            return False
        # Remove types registered by this plugin
        for type_name, plugin_name in list(self._type_providers.items()):
            if plugin_name == name:
                self._types.pop(type_name, None)
                self._type_providers.pop(type_name, None)
        self._plugins.pop(name)
        return True

    def get_plugin(self, name: str) -> MemoryPlugin | None:
        """Look up a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """List all registered plugin names."""
        return list(self._plugins.keys())

    # ── Query ──────────────────────────────────────────────────

    def is_valid_type(self, name: str) -> bool:
        """Check if a type name is registered."""
        return name in self._types

    def get_defaults(self, type_name: str) -> dict:
        """Get default scope, visibility, and required fields for a type."""
        td = self._types.get(type_name)
        if td is None:
            return {}
        return {
            "scope": td.default_scope,
            "visibility": td.default_visibility,
            "required_fields": td.required_fields,
        }
