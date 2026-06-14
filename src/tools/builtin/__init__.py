"""Built-in tools — bash, file operations."""

import subprocess
from pathlib import Path

WORKDIR = Path.cwd()


def safe_path(p: str) -> Path:
    """Prevent directory traversal attacks."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_grep(pattern: str, glob_pattern: str = "**/*") -> str:
    """Search files for a regex pattern."""
    import re
    results = []
    try:
        for f in WORKDIR.glob(glob_pattern):
            if f.is_file() and f.suffix in (".py", ".md", ".json", ".txt", ".ts", ".js", ".yaml", ".yml", ".toml"):
                try:
                    for i, line in enumerate(f.read_text().splitlines(), 1):
                        if re.search(pattern, line):
                            results.append(f"{f}:{i}: {line.strip()[:200]}")
                except Exception:
                    pass
        return "\n".join(results[:100]) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    """List files matching a glob pattern."""
    results = [str(p) for p in WORKDIR.glob(pattern) if p.is_file()]
    return "\n".join(results[:100]) if results else "(no matches)"
