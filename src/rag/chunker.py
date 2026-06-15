"""AST-based Python code chunker.

Splits source files at function / class granularity.
Each chunk carries:
  - Full body of the function / class
  - Adjacent symbol names as context summary
  - File path + line range for traceability
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeChunk:
    """A single chunk of source code."""
    file_path: str          # relative to project root
    symbol_name: str        # function or class name
    symbol_type: str        # "function" | "class" | "module"
    start_line: int
    end_line: int
    code: str               # full source text
    context: list[str] = field(default_factory=list)  # adjacent symbol names
    signature: str = ""     # first line (def/class statement)


def _extract_docstring(body: list[ast.stmt]) -> str:
    """Return the first expression-statement string constant, or ''."""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            return body[0].value.value
    return ""


def chunk_file(file_path: str | Path, source: str = None) -> list[CodeChunk]:
    """Parse a single Python file into chunks.

    Args:
        file_path: relative or absolute path (used as label)
        source:   file contents; read from disk if None

    Returns:
        list of CodeChunk (one per top-level function / class)
    """
    file_path = Path(file_path)
    if source is None:
        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception:
            return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    chunks: list[CodeChunk] = []

    # Collect top-level symbol names for context
    top_symbols: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top_symbols.append(node.name)

    # Build filtered index so context pointers align with top_symbols
    filtered_nodes = [(j, n) for j, n in enumerate(ast.iter_child_nodes(tree))
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    # filtered_idx → position within top_symbols
    for filtered_idx, (orig_idx, node) in enumerate(filtered_nodes):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _add_chunk(file_path, node, lines, top_symbols, filtered_idx, "function", chunks)
        elif isinstance(node, ast.ClassDef):
            _add_chunk(file_path, node, lines, top_symbols, filtered_idx, "class", chunks)
            # Also chunk methods as independent pieces
            method_nodes = [(mj, m) for mj, m in enumerate(node.body)
                          if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            method_symbols = [m.name for _, m in method_nodes]
            for m_filtered_idx, (m_orig_idx, item) in enumerate(method_nodes):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_name = f"{node.name}.{item.name}"
                    _add_chunk(file_path, item, lines, method_symbols,
                              m_filtered_idx, "function", chunks, method_name=method_name)

    # If no functions/classes found, chunk the whole file as one module chunk
    if not chunks:
        chunks.append(CodeChunk(
            file_path=str(file_path),
            symbol_name=file_path.stem,
            symbol_type="module",
            start_line=1,
            end_line=len(lines),
            code=source,
            context=[],
            signature=f"# Module: {file_path.name}",
        ))

    return chunks


def _add_chunk(file_path, node, lines, top_symbols, idx,
               symbol_type, chunks, method_name=None):
    """Build a CodeChunk from an AST node."""
    name = method_name or node.name
    start = node.lineno
    end = node.end_lineno or (len(lines) if hasattr(node, 'end_lineno') else start)

    # Adjacent context: symbols before and after
    context = []
    if idx > 0:
        context.append(top_symbols[idx - 1])
    if idx < len(top_symbols) - 1:
        context.append(top_symbols[idx + 1])

    # First line as signature
    sig = ""
    if start <= len(lines):
        sig = lines[start - 1].strip()

    code = "\n".join(lines[start - 1:end])

    chunks.append(CodeChunk(
        file_path=str(file_path),
        symbol_name=name,
        symbol_type=symbol_type,
        start_line=start,
        end_line=end,
        code=code,
        context=context,
        signature=sig,
    ))


def chunk_directory(root: str | Path, glob_pattern: str = "**/*.py",
                    skip_patterns: list[str] = None) -> list[CodeChunk]:
    """Scan a directory and chunk all matching files.

    Args:
        root:          project root
        glob_pattern:  files to include
        skip_patterns: path substrings to skip (e.g. ['__pycache__', '.git'])

    Returns:
        flat list of CodeChunk
    """
    root = Path(root)
    skip_patterns = skip_patterns or ["__pycache__", ".git", "venv", ".venv", "node_modules"]
    all_chunks: list[CodeChunk] = []

    for fp in root.glob(glob_pattern):
        if any(s in str(fp) for s in skip_patterns):
            continue
        rel = fp.relative_to(root) if fp.is_relative_to(root) else fp
        all_chunks.extend(chunk_file(rel, fp.read_text(encoding="utf-8")))

    return all_chunks
