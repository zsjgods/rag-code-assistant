#!/usr/bin/env python3
"""Example Stop hook: check if model response is complete."""
import json
import sys

data = json.loads(sys.stdin.read())
output = data.get("tool_result", "")

# If response seems incomplete (no code block, ends with a question)
if output.strip().endswith("?") and "```" not in output:
    print("Response appears incomplete — continuing.", file=sys.stderr)
    sys.exit(2)  # Force continue

sys.exit(0)
