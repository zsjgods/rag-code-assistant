"""FileCacheLayer — LRU file content cache with full metadata tracking.

Pure cache — never reads disk. Content is provided by the caller (Read tool,
network fetch, etc.), making it compatible with local, remote, and virtual
workspaces.

Smart truncation for large files:
  - Files ≤ max_lines → cached in full
  - Files > max_lines → only module-level docstring, imports, class/function
    signatures, and decorators are stored. Trailing annotation marks truncation.

Full metadata tracked per entry:
  - sha256 hash (for change detection)
  - mtime (file modification time when cached)
  - size (original byte count)
  - language (detected from file extension)
  - access_count + last_access (for LRU)

The layer renders a compact summary of cached files into the prompt.
Actual content is retrieved via get() / get_info().
"""

import hashlib
import os
import re
import time as time_module
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from src.context.layers.base import BaseLayer


# ── Data model ─────────────────────────────────────────────────────────────


@dataclass
class CachedFile:
    """Full metadata and content for one cached file.

    All metadata is computed at cache time from the provided content
    and file path. Nothing is read from disk by the cache itself.
    """

    path: str                     # Absolute path (used as cache key)
    content: str                  # Stored content (full or smart-extracted)
    full_lines: int               # Actual total lines in the original file
    stored_lines: int             # Lines stored in cache
    is_truncated: bool            # True if file was too large and was truncated

    # ── M2 metadata ─────────────────────────────────────
    file_hash: str                # sha256 of original content (change detection)
    mtime: float                  # os.path.getmtime() when cached
    size: int                     # Original byte count
    language: str                 # Detected from file extension

    # ── Access tracking ─────────────────────────────────
    access_count: int = 0
    last_access: float = 0.0
    timestamp: str = ""           # Human-readable HH:MM:SS of last access


# ── Smart extraction ───────────────────────────────────────────────────────

_SIGNATURE_RE = re.compile(
    r"^(class\s+\w+|def\s+\w+|async\s+def\s+\w+|@\w+)",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(r"^(import\s+|from\s+\S+\s+import\s+)", re.MULTILINE)


def _extract_smart(content: str, max_lines: int) -> tuple[str, int, bool]:
    """Extract a smart preview from file content.

    For files exceeding max_lines, keeps:
      1. Module-level docstring (first triple-quoted string)
      2. All import lines
      3. All class/function/method signatures (with decorators)
      4. A trailing annotation noting the truncation

    Returns: (extracted_text, stored_lines, was_truncated)
    """
    lines = content.split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines:
        return content, total_lines, False

    extracted: list[str] = []
    seen: set[str] = set()
    has_docstring = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Module-level docstring (first occurrence, within first 20 lines)
        if not has_docstring and i < 20 and ('"""' in stripped or "'''" in stripped):
            start = max(0, i - 1)
            end = min(total_lines, i + 10)
            for j in range(start, end):
                s = lines[j].strip()
                if s and s not in seen:
                    extracted.append(lines[j].rstrip())
                    seen.add(s)
            has_docstring = True
            continue

        # Import lines
        if _IMPORT_RE.match(stripped):
            if stripped not in seen:
                extracted.append(line.rstrip())
                seen.add(stripped)
            continue

        # Signatures (class, def, async def, decorators)
        if _SIGNATURE_RE.match(stripped):
            if stripped not in seen:
                extracted.append(line.rstrip())
                seen.add(stripped)
            continue

        # Blank lines for readability between blocks
        if not stripped and extracted and extracted[-1] != "":
            extracted.append("")

    extracted.append("")
    extracted.append(f"# ... file truncated: {total_lines} lines total, showing {len(extracted)} key lines")
    extracted.append("# use Read to see full content")

    return "\n".join(extracted), len(extracted), True


# ── Language detection ─────────────────────────────────────────────────────

_LANG_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".jsx": "JavaScript React",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS", ".sass": "Sass",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".proto": "Protobuf",
    ".xml": "XML",
    ".ipynb": "Jupyter Notebook",
    ".dockerfile": "Dockerfile",
    ".cfg": "Config", ".conf": "Config", ".ini": "Config",
}


def _detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(path)[1].lower()
    return _LANG_MAP.get(ext, "Unknown")


# ── FileCacheLayer ─────────────────────────────────────────────────────────


class FileCacheLayer(BaseLayer):
    """LRU file content cache.

    NEVER reads disk — content must be provided by the caller.
    This makes the cache compatible with remote workspaces (GitHub, SSH, etc.)
    where file content comes from a network fetch, not local I/O.

    On put(), the cache:
      1. Computes sha256 hash (for change detection)
      2. Reads mtime from filesystem metadata (path still valid)
      3. Detects language from extension
      4. Applies smart truncation for large files
      5. Stores with access tracking

    render() outputs a compact summary for the prompt.
    get() / get_info() provide callers with cached content and metadata.
    """

    is_immutable = False

    def __init__(
        self,
        max_files: int = 20,
        max_lines: int = 150,
        enable_smart_truncation: bool = True,
        time_fn: "Callable[[], float] | None" = None,
    ):
        """
        Args:
            max_files: Maximum number of files in the LRU cache.
            max_lines: Files exceeding this line count are smart-truncated.
            enable_smart_truncation: False = always cache full content.
            time_fn: Time function for access tracking (default time.time).
        """
        self._max_files = max_files
        self._max_lines = max_lines
        self._smart = enable_smart_truncation
        self._time_fn = time_fn or time_module.time

        # OrderedDict: most recently accessed at the END (popitem(last=False) drops oldest)
        self._cache: OrderedDict[str, CachedFile] = OrderedDict()

    # ── Identity ─────────────────────────────────────────

    @property
    def name(self) -> str:
        return "file_cache"

    # ── Public API ───────────────────────────────────────

    def put(self, path: str, content: str) -> bool:
        """Cache a file's content.

        Content is REQUIRED — the cache never reads disk.
        Metadata (hash, mtime, size, language) is computed from input.

        Args:
            path: File path (absolute or relative — normalized internally).
            content: Full file content as a string.

        Returns:
            True always (content is stored). Does not raise on missing paths.
        """
        abs_path = os.path.abspath(path)
        original_lines = content.split("\n")
        full_lines = len(original_lines)
        byte_size = len(content.encode("utf-8"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # mtime from filesystem (path may be valid even in remote scenarios)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            mtime = 0.0

        language = _detect_language(abs_path)

        # Smart truncation
        if self._smart and full_lines > self._max_lines:
            stored_content, stored_lines, is_truncated = _extract_smart(
                content, self._max_lines
            )
        else:
            stored_content, stored_lines, is_truncated = content, full_lines, False

        now = self._time_fn()

        if abs_path in self._cache:
            existing = self._cache[abs_path]
            existing.content = stored_content
            existing.full_lines = full_lines
            existing.stored_lines = stored_lines
            existing.is_truncated = is_truncated
            existing.file_hash = content_hash
            existing.mtime = mtime
            existing.size = byte_size
            existing.language = language
            existing.access_count += 1
            existing.last_access = now
            existing.timestamp = datetime.fromtimestamp(now).strftime("%H:%M:%S")
            self._cache.move_to_end(abs_path)
        else:
            self._cache[abs_path] = CachedFile(
                path=abs_path,
                content=stored_content,
                full_lines=full_lines,
                stored_lines=stored_lines,
                is_truncated=is_truncated,
                file_hash=content_hash,
                mtime=mtime,
                size=byte_size,
                language=language,
                access_count=1,
                last_access=now,
                timestamp=datetime.fromtimestamp(now).strftime("%H:%M:%S"),
            )

        # LRU eviction
        while len(self._cache) > self._max_files:
            self._cache.popitem(last=False)

        return True

    def get(self, path: str) -> str | None:
        """Retrieve cached content for a file path.

        Returns stored content (full or smart-truncated), or None if
        the file is not in cache. Updates access tracking.
        """
        entry = self._get_entry(path)
        return entry.content if entry else None

    def get_info(self, path: str) -> CachedFile | None:
        """Retrieve full CachedFile metadata + content.

        Useful for callers that need hash, mtime, language, etc.
        """
        return self._get_entry(path)

    def _get_entry(self, path: str) -> CachedFile | None:
        """Internal: get CachedFile entry with access tracking."""
        abs_path = os.path.abspath(path)
        entry = self._cache.get(abs_path)
        if entry is None:
            return None

        entry.access_count += 1
        entry.last_access = self._time_fn()
        entry.timestamp = datetime.fromtimestamp(entry.last_access).strftime("%H:%M:%S")
        self._cache.move_to_end(abs_path)
        return entry

    def invalidate(self, path: str) -> bool:
        """Remove a file from the cache (e.g. after modification).

        Returns True if the file was cached, False otherwise.
        """
        abs_path = os.path.abspath(path)
        if abs_path in self._cache:
            del self._cache[abs_path]
            return True
        return False

    def has(self, path: str) -> bool:
        """Check if a file is cached without altering access tracking."""
        return os.path.abspath(path) in self._cache

    @property
    def size(self) -> int:
        """Number of cached files."""
        return len(self._cache)

    @property
    def cached_paths(self) -> list[str]:
        """All cached paths, most recently accessed first."""
        return list(reversed(list(self._cache.keys())))

    # ── Render (compact summary for prompt) ──────────────

    def render(self) -> str:
        """Render a compact summary of cached files.

        Output:
          <file-cache>
          - src/foo.py (245 lines, full) [accessed 1m ago]
          - src/bar.py (1200 lines, signature-only) [accessed 5m ago]
          </file-cache>

        Returns empty string if cache is empty.
        """
        if not self._cache:
            return ""

        lines: list[str] = []
        now = self._time_fn()

        for path, entry in reversed(list(self._cache.items())):
            try:
                display = os.path.relpath(path)
            except ValueError:
                display = path

            badge = (
                f"{entry.full_lines} lines, signature-only"
                if entry.is_truncated
                else f"{entry.full_lines} lines, full"
            )

            delta = now - entry.last_access
            ago = (
                "just now" if delta < 60 else
                f"{int(delta // 60)}m ago" if delta < 3600 else
                f"{int(delta // 3600)}h ago"
            )

            lines.append(f"- {display} ({badge}) [accessed {ago}]")

        body = "\n".join(lines)
        return f"<file-cache>\n{body}\n</file-cache>"

    # ── BaseLayer interface ──────────────────────────────

    def clear(self) -> None:
        """Remove all cached files."""
        self._cache.clear()

    def token_count(self) -> int:
        """Estimate tokens from stored content only."""
        return sum(len(e.content) // 4 for e in self._cache.values())
