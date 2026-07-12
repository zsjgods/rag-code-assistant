"""Scratchpad — permission-free shared file space for cross-agent knowledge.

Physical location: /tmp/s_full_{session_id}/scratchpad/
  - No permission prompts: agents read/write freely
  - Durable cross-worker knowledge: agent A writes, agent B reads
  - Session isolation: each session gets its own scratchpad
  - Structure-free: agents organize files as they see fit
"""

import os
import uuid
from pathlib import Path


class Scratchpad:
    """Shared file space for agent collaboration."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self._dir = Path(f"/tmp/s_full_{self.session_id}/scratchpad")
        os.makedirs(self._dir, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._dir

    def write(self, filename: str, content: str) -> str:
        """Write to scratchpad. No permission check."""
        fp = self._dir / filename
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return str(fp)

    def read(self, filename: str) -> str:
        """Read from scratchpad. No permission check."""
        fp = self._dir / filename
        if not fp.exists():
            return f"(scratchpad file not found: {filename})"
        return fp.read_text(encoding="utf-8")

    def ls(self) -> list[str]:
        """List all files in scratchpad."""
        return [str(p.relative_to(self._dir)) for p in self._dir.rglob("*") if p.is_file()]

    def cleanup(self) -> None:
        """Remove scratchpad directory."""
        import shutil
        if self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)
