#!/usr/bin/env python3
"""Example PostToolUse hook: audit log file writes."""
import json
import sys
from datetime import datetime

data = json.loads(sys.stdin.read())
tool_input = data.get("tool_input", {})
path = tool_input.get("path", "unknown")

# Audit log: record the write
with open("/tmp/s_full_audit.log", "a") as f:
    f.write(f"[{datetime.now().isoformat()}] WRITE: {path}\n")

print(json.dumps({"decision": "approve"}))
sys.exit(0)
