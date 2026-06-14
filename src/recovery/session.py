"""Session persistence — bridgePointer for crash recovery.

Saves three fields to disk as JSON: sessionId, lastMessageId, mtime.
mtime acts as a freshness indicator.
"""

import json
import time
import uuid
from pathlib import Path


class SessionState:
    """Persistent session state for crash recovery."""

    def __init__(self, workdir: Path | None = None):
        wd = workdir or Path.cwd()
        self._file = wd / ".s_full_session.json"
        self._state = self._load()

    def _load(self) -> dict:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        return self._fresh()

    def _fresh(self) -> dict:
        return {
            "sessionId": str(uuid.uuid4())[:8],
            "lastMessageId": "",
            "mtime": time.time(),
        }

    def _save(self):
        self._state["mtime"] = time.time()
        self._file.write_text(json.dumps(self._state, indent=2))

    @property
    def session_id(self) -> str:
        return self._state["sessionId"]

    def update_last_message(self, msg_id: str):
        self._state["lastMessageId"] = msg_id
        self._save()

    @property
    def freshness(self) -> float:
        """Seconds since last state change."""
        return time.time() - self._state["mtime"]

    def resume(self) -> dict | None:
        """Check if a session can be resumed.

        Returns session state if resumable, None if too stale.
        """
        if self.freshness > 3600:  # Stale after 1 hour
            return None
        if not self._state.get("lastMessageId"):
            return None
        return dict(self._state)
