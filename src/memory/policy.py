"""Memory Policy Engine — rule-based plugin system for memory governance.

Instead of hardcoded if/else chains, PolicyEngine uses a registry of PolicyRule
plugins. Each rule is a standalone check that returns (allowed, reason).

Built-in rules:
  - TypeAllowRule:       allow/block specific MemoryTypes
  - ContentLengthRule:   min/max content length
  - ContentPatternRule:  regex forbidden patterns (PII, passwords, etc.)
  - DuplicateRule:       allow/block exact hash duplicates
  - ScopeLimitRule:      max entries per MemoryScope
  - TypeLimitRule:       max entries per MemoryType
  - SourceRule:          allow/block specific sources

Custom rules: subclass PolicyRule and register via engine.register_rule().
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.memory.types import MemoryEntry, MemoryScope, MemoryType


# ═══════════════════════════════════════════════════════════════════
# PolicyRule ABC
# ═══════════════════════════════════════════════════════════════════

class PolicyRule(ABC):
    """Abstract policy rule. Each rule checks one dimension of memory governance."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique rule name (e.g. 'type_allow', 'content_length')."""
        ...

    @abstractmethod
    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        """Check if entry passes this rule.

        Args:
            entry: The memory entry being validated.
            context: Arbitrary context dict (e.g. current store stats, counts, etc.).

        Returns:
            (allowed: bool, reason: str)
        """
        ...

    def priority(self) -> int:
        """Lower = runs earlier. Default 50."""
        return 50


# ═══════════════════════════════════════════════════════════════════
# Built-in Rules
# ═══════════════════════════════════════════════════════════════════

class TypeAllowRule(PolicyRule):
    """Allow only specific MemoryTypes. None = allow all."""

    name = "type_allow"

    def __init__(self, allowed_types: list[MemoryType] | None = None):
        self._allowed = allowed_types  # None = allow all

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        if self._allowed is None:
            return True, "ok"
        if entry.type not in self._allowed:
            return False, f"MemoryType '{entry.type.value}' is not allowed"
        return True, "ok"

    def priority(self) -> int:
        return 10  # Run early — cheap check


class ContentLengthRule(PolicyRule):
    """Enforce min/max content text length."""

    name = "content_length"

    def __init__(self, min_length: int = 10, max_length: int = 10000):
        self._min = min_length
        self._max = max_length

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        text_len = len(entry.content.text)
        if text_len < self._min:
            return False, f"Content too short ({text_len} < {self._min})"
        if text_len > self._max:
            return False, f"Content too long ({text_len} > {self._max})"
        return True, "ok"

    def priority(self) -> int:
        return 20


class ContentPatternRule(PolicyRule):
    """Forbid content matching regex patterns (PII, passwords, secrets)."""

    name = "content_pattern"

    def __init__(self, forbidden_patterns: list[str] | None = None):
        self._patterns: list[re.Pattern] = [
            re.compile(p) for p in (forbidden_patterns or [])
        ]

    def add_pattern(self, pattern: str) -> None:
        """Add a forbidden regex pattern at runtime."""
        self._patterns.append(re.compile(pattern))

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        for pat in self._patterns:
            match = pat.search(entry.content.text)
            if match:
                return False, f"Content matches forbidden pattern: {pat.pattern}"
        # Also check summary
        for pat in self._patterns:
            if pat.search(entry.content.summary):
                return False, f"Summary matches forbidden pattern: {pat.pattern}"
        return True, "ok"

    def priority(self) -> int:
        return 15  # Before content_length — block sensitive content fast


class DuplicateRule(PolicyRule):
    """Allow or block exact hash duplicates."""

    name = "duplicate"

    def __init__(self, allow_duplicates: bool = False):
        self._allow_duplicates = allow_duplicates

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        if self._allow_duplicates:
            return True, "ok"
        # Check context for existing hash
        existing_hash = context.get("content_hash", "")
        if existing_hash and existing_hash == entry.content.hash:
            return False, f"Duplicate content (hash={entry.content.hash[:8]}...)"
        return True, "ok"

    def priority(self) -> int:
        return 30


class ScopeLimitRule(PolicyRule):
    """Limit max entries per MemoryScope."""

    name = "scope_limit"

    def __init__(self, max_per_scope: dict[MemoryScope, int] | None = None):
        self._limits = max_per_scope or {}

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        limit = self._limits.get(entry.scope)
        if limit is None:
            return True, "ok"
        current_count = context.get("scope_counts", {}).get(entry.scope.value, 0)
        if current_count >= limit:
            return False, f"Scope '{entry.scope.value}' limit reached ({current_count}/{limit})"
        return True, "ok"

    def priority(self) -> int:
        return 40


class TypeLimitRule(PolicyRule):
    """Limit max entries per MemoryType."""

    name = "type_limit"

    def __init__(self, max_per_type: dict[MemoryType, int] | None = None):
        self._limits = max_per_type or {}

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        limit = self._limits.get(entry.type)
        if limit is None:
            return True, "ok"
        current_count = context.get("type_counts", {}).get(entry.type.value, 0)
        if current_count >= limit:
            return False, f"Type '{entry.type.value}' limit reached ({current_count}/{limit})"
        return True, "ok"

    def priority(self) -> int:
        return 41


class SourceRule(PolicyRule):
    """Allow or block specific sources."""

    name = "source"

    def __init__(self, allowed_sources: list[str] | None = None):
        self._allowed = allowed_sources  # None = allow all

    def check(self, entry: MemoryEntry, context: dict) -> tuple[bool, str]:
        if self._allowed is None:
            return True, "ok"
        if entry.content.source not in self._allowed:
            return False, f"Source '{entry.content.source}' is not allowed"
        return True, "ok"

    def priority(self) -> int:
        return 50


# ═══════════════════════════════════════════════════════════════════
# PolicyEngine
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PolicyResult:
    """Result of a full policy check."""
    allowed: bool
    reason: str
    blocked_by: list[str] = field(default_factory=list)  # Rule names that blocked


class PolicyEngine:
    """Rule-based policy engine with plugin architecture.

    Rules are checked in priority order (lowest first). The first blocking
    rule stops the chain and returns its reason. If all rules pass, the entry
    is allowed.

    Usage:
        engine = PolicyEngine()
        engine.register_rule(TypeAllowRule(allowed_types=[MemoryType.USER]))
        engine.register_rule(ContentLengthRule(min_length=5))
        ok, reason, blocked = engine.check(entry, store_context)
    """

    def __init__(self):
        self._rules: list[PolicyRule] = []

    def register_rule(
        self,
        rule: PolicyRule,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Register a rule, optionally positioning it relative to another rule.

        Args:
            rule: The rule to register.
            before: Place BEFORE the rule with this name.
            after: Place AFTER the rule with this name.
        """
        # Remove existing rule with same name
        self.remove_rule(rule.name)

        # Find insertion position
        if before:
            idx = self._find_index(before)
            if idx >= 0:
                self._rules.insert(idx, rule)
                return
        if after:
            idx = self._find_index(after)
            if idx >= 0:
                self._rules.insert(idx + 1, rule)
                return

        # Default: append, then sort by priority
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority())

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found."""
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                self._rules.pop(i)
                return True
        return False

    def get_rule(self, name: str) -> PolicyRule | None:
        """Look up a rule by name."""
        for rule in self._rules:
            if rule.name == name:
                return rule
        return None

    def list_rules(self) -> list[str]:
        """List all registered rule names in execution order."""
        return [r.name for r in self._rules]

    def check(self, entry: MemoryEntry, context: dict | None = None) -> tuple[bool, str, list[str]]:
        """Run all rules against an entry.

        Args:
            entry: The memory entry to check.
            context: Arbitrary context dict (store stats, counts, etc.).

        Returns:
            (allowed: bool, reason: str, blocked_by: list[str])
        """
        ctx = context or {}
        blocked_by: list[str] = []

        for rule in self._rules:
            allowed, reason = rule.check(entry, ctx)
            if not allowed:
                blocked_by.append(rule.name)
                return False, reason, blocked_by

        return True, "ok", []

    def _find_index(self, name: str) -> int:
        """Find the index of a rule by name. Returns -1 if not found."""
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                return i
        return -1
