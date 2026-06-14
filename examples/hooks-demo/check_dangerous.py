#!/usr/bin/env python3
"""Example PreToolUse hook: block dangerous commands."""
import json
import sys

data = json.loads(sys.stdin.read())
command = data.get("tool_input", {}).get("command", "")

dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
for d in dangerous:
    if d in command:
        print(json.dumps({
            "decision": "block",
            "reason": f"Blocked dangerous command pattern: '{d}'"
        }))
        sys.exit(2)

print(json.dumps({"decision": "approve"}))
sys.exit(0)
