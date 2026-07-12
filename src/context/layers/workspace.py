"""WorkspaceLayer — tracks runtime workspace state for the agent.

Maintains the live view of where the agent is and what it's working on:

  - CWD (current working directory)
  - Git branch + dirty files
  - Open / recent files
  - Current task description

This layer is about RUNTIME STATE ONLY. Static project metadata
(project type, tech stack, entry files) belongs to src.context.detector
and is fetched on demand, not per-render.

Render output is kept minimal to avoid bloat in the system prompt.
"""

import os
import subprocess

from src.context.layers.base import BaseLayer


# ── Git helpers ────────────────────────────────────────────────────────────


def _get_git_branch(path: str) -> str:
    """Get current git branch name, or empty string if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=path,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _get_dirty_files(path: str) -> list[str]:
    """Get list of files modified vs HEAD, or empty if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=path,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        dirty = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # porcelain: " M src/foo.py" or "?? new.txt"
            parts = line.split(None, 1)
            if len(parts) == 2:
                dirty.append(parts[1])
        return dirty
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


# ── WorkspaceLayer ─────────────────────────────────────────────────────────


class WorkspaceLayer(BaseLayer):
    """Tracks workspace runtime state.

    Responsibilities:
      - CWD tracking (updated via set_cwd or directory_changed event)
      - Git state (branch, dirty files — refreshed on demand)
      - Open files (files currently being worked on, ordered by access)
      - Recent files (LRU-ordered list of recently accessed files)
      - Current task description

    Non-responsibilities (handled by src.context.detector):
      - Project type detection
      - Tech stack scanning
      - Entry file discovery

    Render output (added to system prompt):
      <workspace-context>
      CWD: /path
      Branch: main
      Open Files: src/foo.py, src/bar.py
      Dirty Files: src/foo.py
      Current Task: Fixing bug in X
      </workspace-context>

    Fields that are empty or absent are omitted.
    """

    is_immutable = False

    def __init__(
        self,
        cwd: str | None = None,
        max_open_files: int = 20,
        max_recent_files: int = 30,
    ):
        self._cwd: str = os.path.abspath(cwd) if cwd else os.getcwd()
        self._max_open_files = max_open_files
        self._max_recent_files = max_recent_files

        # ── Git state ────────────────────────────────────
        self._git_branch: str = ""
        self._dirty_files: list[str] = []

        # ── File tracking ────────────────────────────────
        self._open_files: list[str] = []
        self._recent_files: list[str] = []

        # ── Task ─────────────────────────────────────────
        self._current_task: str = ""

        # Initial git refresh
        self.refresh_git_state()

    # ── Identity ─────────────────────────────────────────

    @property
    def name(self) -> str:
        return "workspace"

    # ── Render (minimal — only what's needed per round) ──

    def render(self) -> str:
        """Format runtime workspace state as a compact context block.

        Only non-empty fields are included. Empty lines are omitted.
        """
        lines: list[str] = [f"CWD: {self._cwd}"]

        if self._git_branch:
            lines.append(f"Branch: {self._git_branch}")

        if self._open_files:
            shown = self._open_files[:10]
            text = f"Open Files: {', '.join(shown)}"
            if len(self._open_files) > 10:
                text += f" (+{len(self._open_files) - 10} more)"
            lines.append(text)

        if self._dirty_files:
            shown = self._dirty_files[:8]
            text = f"Dirty Files: {', '.join(shown)}"
            if len(self._dirty_files) > 8:
                text += f" (+{len(self._dirty_files) - 8} more)"
            lines.append(text)

        if self._current_task:
            lines.append(f"Current Task: {self._current_task}")

        body = "\n".join(lines)
        return f"<workspace-context>\n{body}\n</workspace-context>"

    # ── Git operations ───────────────────────────────────

    def refresh_git_state(self) -> None:
        """Refresh git branch and dirty files from the filesystem.

        Safe to call frequently — returns fast for non-git directories.
        """
        self._git_branch = _get_git_branch(self._cwd)
        self._dirty_files = _get_dirty_files(self._cwd)

    # ── CWD ──────────────────────────────────────────────

    def set_cwd(self, path: str) -> None:
        """Update current working directory and refresh git state."""
        self._cwd = os.path.abspath(path)
        self.refresh_git_state()

    # ── File tracking ────────────────────────────────────

    def file_opened(self, path: str) -> None:
        """Record that a file was opened / read.

        Updates both open_files (ordered set) and recent_files (LRU).
        """
        abs_path = os.path.abspath(path)

        # Open files: append if new, keep bounded
        if abs_path not in self._open_files:
            self._open_files.append(abs_path)
            if len(self._open_files) > self._max_open_files:
                self._open_files.pop(0)

        # Recent files: move to end (most recent = last)
        if abs_path in self._recent_files:
            self._recent_files.remove(abs_path)
        self._recent_files.append(abs_path)
        if len(self._recent_files) > self._max_recent_files:
            self._recent_files.pop(0)

    def file_modified(self, path: str) -> None:
        """Record that a file was edited / written.

        Adds to open_files and marks as dirty.
        """
        abs_path = os.path.abspath(path)
        self.file_opened(abs_path)

        if abs_path not in self._dirty_files:
            self._dirty_files.append(abs_path)
            if len(self._dirty_files) > 20:
                self._dirty_files = self._dirty_files[-20:]

    def file_closed(self, path: str) -> None:
        """Remove a file from open_files list."""
        abs_path = os.path.abspath(path)
        if abs_path in self._open_files:
            self._open_files.remove(abs_path)

    # ── Task ─────────────────────────────────────────────

    def set_current_task(self, task: str) -> None:
        """Set the agent's current task description."""
        self._current_task = task

    # ── BaseLayer interface ──────────────────────────────

    def clear(self) -> None:
        """Clear dynamic state (open files, recent files, current task).

        Preserves CWD and git state.
        """
        self._open_files.clear()
        self._recent_files.clear()
        self._current_task = ""

    # ── Accessors ────────────────────────────────────────

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def git_branch(self) -> str:
        return self._git_branch

    @property
    def open_files(self) -> list[str]:
        return list(self._open_files)

    @property
    def dirty_files(self) -> list[str]:
        return list(self._dirty_files)

    @property
    def recent_files(self) -> list[str]:
        return list(self._recent_files)

    @property
    def current_task(self) -> str:
        return self._current_task

    # ── Bulk update from tool calls (legacy compat) ──────

    def update_from_tool(self, tool_name: str, args: dict | None = None) -> None:
        """Infer workspace state changes from tool calls.

        Primary integration path is now through event hooks
        (on_file_read, on_file_write, on_directory_changed).
        This method is maintained for backward compatibility.
        """
        args = args or {}

        if tool_name in ("Read", "read", "read_file"):
            path = args.get("file_path", "")
            if path:
                self.file_opened(path)

        elif tool_name in ("Edit", "edit", "Write", "write", "write_file"):
            path = args.get("file_path", "")
            if path:
                self.file_modified(path)

        elif tool_name == "Glob":
            path = args.get("path", self._cwd)
            if path:
                self.file_opened(path)

        elif tool_name == "Bash":
            cmd = (args.get("command") or "").strip()
            if cmd.startswith("cd "):
                target = cmd[3:].strip().strip("\"'")
                if target:
                    new_cwd = os.path.normpath(
                        os.path.join(self._cwd, target)
                    ) if not os.path.isabs(target) else target
                    self.set_cwd(new_cwd)
            elif "git" in cmd and any(kw in cmd for kw in ("branch", "status", "checkout", "pull", "merge", "commit")):
                self.refresh_git_state()
