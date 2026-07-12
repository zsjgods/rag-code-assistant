"""Migration — schema version migration for recovered state.

MigrationRegistry maps (from_version, to_version) → migration_fn.

Migration functions receive the raw dict and return the transformed dict.
They are applied in sequence for multi-step upgrades (1.0 → 1.1 → 2.0).

Usage:
    registry = MigrationRegistry()
    registry.register("1.0", "1.1", my_migration_fn)
    result = registry.migrate(data, "1.0", "1.1")
"""

from dataclasses import dataclass, field
from typing import Callable


class MigrationError(Exception):
    """Raised when a migration step fails or the version path is unknown."""
    pass


# ── Migration function type ────────────────────────────────────────────

MigrationFn = Callable[[dict], dict]
"""A migration function receives a raw data dict and returns a transformed dict."""


# ── MigrationRegistry ──────────────────────────────────────────────────


@dataclass
class MigrationStep:
    """A single version-to-version transformation."""

    from_version: str
    to_version: str
    fn: MigrationFn
    description: str = ""


class MigrationRegistry:
    """Registry of version migration steps.

    Supports:
      - register(from_ver, to_ver, fn) — add a migration step
      - migrate(data, from_ver, to_ver) — run all steps in sequence
      - can_migrate(from_ver, to_ver) — check if a path exists
      - find_path(from_ver, to_ver) — return the step list
    """

    def __init__(self):
        # Key: (from_version, to_version) → MigrationStep
        self._steps: dict[tuple[str, str], MigrationStep] = {}

    def register(
        self,
        from_version: str,
        to_version: str,
        fn: MigrationFn,
        description: str = "",
    ) -> None:
        """Register a migration step.

        Args:
            from_version: Source schema version.
            to_version: Target schema version.
            fn: Migration function: dict → dict.
            description: Human-readable description of the change.
        """
        key = (from_version, to_version)
        if key in self._steps:
            raise ValueError(
                f"Migration step {from_version} → {to_version} already registered"
            )
        self._steps[key] = MigrationStep(
            from_version=from_version,
            to_version=to_version,
            fn=fn,
            description=description,
        )

    def can_migrate(self, from_version: str, to_version: str) -> bool:
        """Check whether a migration path exists (BFS over steps).

        Args:
            from_version: Current schema version.
            to_version: Target schema version.

        Returns:
            True if at least one migration path exists.
        """
        try:
            self.find_path(from_version, to_version)
            return True
        except MigrationError:
            return False

    def find_path(self, from_version: str, to_version: str) -> list[MigrationStep]:
        """Find the shortest migration path between two versions.

        Uses BFS over the graph of registered steps.

        Args:
            from_version: Current schema version.
            to_version: Target schema version.

        Returns:
            Ordered list of MigrationSteps to apply.

        Raises:
            MigrationError: If no path exists.
        """
        if from_version == to_version:
            return []

        # BFS
        visited: set[str] = {from_version}
        queue: list[tuple[str, list[MigrationStep]]] = [(from_version, [])]

        while queue:
            current, path = queue.pop(0)

            for (f, t), step in self._steps.items():
                if f == current and t not in visited:
                    new_path = path + [step]
                    if t == to_version:
                        return new_path
                    visited.add(t)
                    queue.append((t, new_path))

        raise MigrationError(
            f"No migration path from {from_version} to {to_version}. "
            f"Registered steps: {list(self._steps.keys())}"
        )

    def migrate(self, data: dict, from_version: str, to_version: str) -> dict:
        """Migrate data from one schema version to another.

        Applies all steps in the shortest path sequentially.

        Args:
            data: Raw data dict in from_version format.
            from_version: Current schema version.
            to_version: Target schema version.

        Returns:
            Transformed data dict in to_version format.

        Raises:
            MigrationError: If no path exists or a step fails.
        """
        if from_version == to_version:
            return dict(data)

        path = self.find_path(from_version, to_version)
        result = dict(data)

        for step in path:
            try:
                result = step.fn(result)
            except Exception as e:
                raise MigrationError(
                    f"Migration step {step.from_version} → {step.to_version} failed: {e}"
                ) from e

        return result

    @property
    def steps(self) -> list[MigrationStep]:
        """All registered migration steps."""
        return list(self._steps.values())

    def clear(self) -> None:
        """Remove all registered steps (for testing)."""
        self._steps.clear()
