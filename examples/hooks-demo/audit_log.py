#!/usr/bin/env python3
"""PostToolUse hook: audit every tool call to a log file.

Reads hook input from stdin, writes a one-line JSON record
to /tmp/s_full_audit.jsonl for every tool invocation.
"""
import json
import os
import sys
from datetime import datetime

data = json.loads(sys.stdin.read())

tool_name = data.get("tool_name", "?")
tool_input = data.get("tool_input", {})
tool_result = data.get("tool_result", "")[:200]  # truncate
event = data.get("event", "")

# Build audit record
record = {
    "ts": datetime.now().isoformat(),
    "event": event,
    "tool": tool_name,
    "input_summary": str(tool_input)[:200],
    "result_summary": tool_result,
}

# Append to audit log
log_path = "/tmp/s_full_audit.jsonl"
os.makedirs(os.path.dirname(log_path), exist_ok=True)
with open(log_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")

# Always approve — audit doesn't block
print(json.dumps({"decision": "approve"}))
sys.exit(0)
