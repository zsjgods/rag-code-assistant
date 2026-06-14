"""Observable state store — 35-line reactive state management.

getState/setState/subscribe pattern. onChange() dispatches to all listeners.
Sub-agents can have their setAppState replaced with no-op for isolation.
"""

from typing import Any, Callable


class Store:
    """Minimal reactive store with subscription support."""

    def __init__(self, initial: dict | None = None):
        self._state: dict = initial or {}
        self._listeners: list[Callable[[str, Any, Any], None]] = []

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        old = self._state.get(key)
        self._state[key] = value
        self._on_change(key, old, value)

    def update(self, updates: dict) -> None:
        for k, v in updates.items():
            self.set(k, v)

    def subscribe(self, listener: Callable[[str, Any, Any], None]) -> Callable:
        """Subscribe to state changes. Returns unsubscribe function."""
        self._listeners.append(listener)
        def unsubscribe():
            self._listeners.remove(listener)

        return unsubscribe

    def _on_change(self, key: str, old: Any, new: Any) -> None:
        for listener in self._listeners:
            try:
                listener(key, old, new)
            except Exception:
                pass

    def snapshot(self) -> dict:
        return dict(self._state)


class ToolUseContext:
    """Execution context for a tool invocation.

    Sub-agents get a context where setAppState is a no-op by default
    (isolation), but setAppStateForTasks always penetrates (task state sharing).
    """

    def __init__(self, store: Store, isolated: bool = False):
        self.store = store
        self.isolated = isolated
        self._file_state: dict = {}  # Per-context file state cache

    def read_file_state(self, path: str) -> Any:
        """Read file state — deep copy for isolation."""
        import copy
        state = self._file_state.get(path)
        return copy.deepcopy(state) if state is not None else None

    def set_file_state(self, path: str, state: Any) -> None:
        """Set file state in this context."""
        self._file_state[path] = state

    def set_app_state(self, key: str, value: Any) -> None:
        """Set application state — no-op if isolated (sub-agent boundary)."""
        if self.isolated:
            return  # Isolation: sub-agent state changes don't leak
        self.store.set(key, value)

    def set_app_state_for_tasks(self, key: str, value: Any) -> None:
        """Set task-related state — always penetrates isolation."""
        self.store.set(key, value)  # Tasks always shared
