#!/usr/bin/env python3
"""UserPromptSubmit hook: inject environment context into each user message.

Reads the hook input JSON from stdin, extracts the user_message,
and returns additionalContext with current time, cwd, and Python version.
"""
import json
import os
import sys
from datetime import datetime

# Hook input comes via stdin
data = json.loads(sys.stdin.read())

user_msg = data.get("user_message", "")
event = data.get("event", "")

# Build additional context
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
context_parts = [
    f"Time: {now}",
    f"CWD: {os.getcwd()}",
    f"Python: {sys.version.split()[0]}",
]

context_text = " | ".join(context_parts)

# Always approve — just inject context
print(json.dumps({
    "decision": "approve",
    "additionalContext": context_text,
}))

sys.exit(0)
