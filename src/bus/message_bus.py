"""MessageBus — JSONL-based inter-agent communication.

Supports: message, broadcast, shutdown_request, shutdown_response,
plan_approval_response. One .jsonl file per recipient.
"""

import json
import time
from pathlib import Path


VALID_TYPES = {"message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"}


class MessageBus:
    """JSONL file-based message bus for agent communication."""

    def __init__(self, workdir: Path | None = None):
        wd = workdir or Path.cwd()
        self.inbox_dir = wd / ".team" / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict | None = None) -> str:
        if msg_type not in VALID_TYPES:
            return f"Error: Invalid message type '{msg_type}'"

        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)

        with open(self.inbox_dir / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = self.inbox_dir / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")  # Drain
        return msgs

    def broadcast(self, sender: str, content: str, names: list[str]) -> str:
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"
