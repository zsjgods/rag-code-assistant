"""Quick smoke tests for the hook system."""

import sys
sys.path.insert(0, ".")

from src.agent.hooks import HookManager, HookConfig, HookInput


def test_hook_registration():
    """Hooks can be registered and retrieved by event."""
    hm = HookManager()
    h = HookConfig(type="command", matcher="Bash", command="echo test")
    hm.register("PreToolUse", h)

    matching = hm._get_matching("PreToolUse", "Bash")
    assert len(matching) == 1
    assert matching[0].matcher == "Bash"


def test_hook_blocking():
    """A hook returning exit code 2 blocks the tool."""
    hm = HookManager()
    h = HookConfig(
        type="command",
        matcher="Bash",
        command="exit 2",  # Simulate block
    )
    hm.register("PreToolUse", h)

    result = hm.execute("PreToolUse", HookInput(
        event="PreToolUse", tool_name="Bash",
        tool_input={"command": "rm something"},
    ))

    assert result.is_blocked


def test_priority_ordering():
    """Local hooks execute before project hooks."""
    hm = HookManager()
    hm.register("PreToolUse", HookConfig(type="command", command="echo p", priority="project"))
    hm.register("PreToolUse", HookConfig(type="command", command="echo l", priority="local"))
    hm._sort_by_priority()

    matching = hm._get_matching("PreToolUse")
    assert matching[0].priority == "local"
    assert matching[1].priority == "project"


def test_hook_disabled():
    """Global disable blocks all hooks."""
    hm = HookManager()
    hm.register("PreToolUse", HookConfig(type="command", command="echo test"))
    hm.disable_all()

    matching = hm._get_matching("PreToolUse")
    assert len(matching) == 0


def test_hook_input():
    """HookInput collects event data correctly."""
    hi = HookInput(
        event="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "ls"},
    )
    assert hi.event == "PreToolUse"
    assert hi.tool_name == "Bash"
    assert hi.tool_input["command"] == "ls"


if __name__ == "__main__":
    test_hook_registration()
    test_hook_blocking()
    test_priority_ordering()
    test_hook_disabled()
    test_hook_input()
    print("All hook tests passed!")
