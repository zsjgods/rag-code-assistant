"""Index management — build, save, load the RAG index."""

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

from .chunker import CodeChunk, chunk_directory
from .embedder import Embedder


@dataclass
class Index:
    """Serialisable index of all code chunks."""
    chunks: list[CodeChunk] = field(default_factory=list)
    embedder: Embedder = field(default_factory=Embedder)
    source_root: str = ""
    file_count: int = 0

    def __len__(self):
        return len(self.chunks)


class Indexer:
    """Build and persist a code index for a project."""

    def __init__(self, store_dir: str | Path = None):
        self.store_dir = Path(store_dir) if store_dir else Path.cwd() / ".rag_index"
        self.index = Index()

    # ── build ────────────────────────────────────────────────

    def build(self, root: str | Path, glob_pattern: str = "**/*.py",
              skip_patterns: list[str] = None, force: bool = False) -> Index:
        """Scan and index a project directory.

        Args:
            root:          project root to scan
            glob_pattern:  file pattern
            skip_patterns: directories / patterns to skip
            force:         rebuild even if cached index exists

        Returns:
            Index with chunks + fitted embedder
        """
        root = Path(root).resolve()
        cache_path = self.store_dir / "index.pkl"

        # Return cached if fresh
        if not force and cache_path.exists():
            return self.load()

        # Chunk
        chunks = chunk_directory(root, glob_pattern, skip_patterns)
        if not chunks:
            raise ValueError(f"No code chunks found in {root}")

        # Fit embedder
        documents = [_chunk_text(c) for c in chunks]
        embedder = Embedder()
        embedder.fit(documents)

        self.index = Index(
            chunks=chunks,
            embedder=embedder,
            source_root=str(root),
            file_count=len(set(c.file_path for c in chunks)),
        )

        # Persist
        self.save()

        return self.index

    # ── persistence ──────────────────────────────────────────

    def save(self):
        """Write index to disk as pickle + metadata JSON."""
        self.store_dir.mkdir(parents=True, exist_ok=True)

        # Embedder separately (contains sklearn objects)
        self.index.embedder.save(self.store_dir / "embedder.pkl")

        # Chunk metadata as JSON (human-readable)
        chunks_meta = []
        for c in self.index.chunks:
            chunks_meta.append({
                "file": c.file_path,
                "name": c.symbol_name,
                "type": c.symbol_type,
                "lines": f"{c.start_line}-{c.end_line}",
                "signature": c.signature,
                "context": c.context,
            })
        (self.store_dir / "chunks.json").write_text(
            json.dumps(chunks_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Full index metadata
        meta = {
            "source_root": self.index.source_root,
            "file_count": self.index.file_count,
            "chunk_count": len(self.index.chunks),
        }
        (self.store_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Full chunks (code bodies) as pickle
        with open(self.store_dir / "chunks.pkl", "wb") as f:
            pickle.dump(self.index.chunks, f)

    def load(self) -> Index:
        """Load index from disk."""
        if not (self.store_dir / "embedder.pkl").exists():
            raise FileNotFoundError(f"No index at {self.store_dir} — run build() first")

        embedder = Embedder()
        embedder.load(self.store_dir / "embedder.pkl")

        with open(self.store_dir / "chunks.pkl", "rb") as f:
            chunks = pickle.load(f)

        meta_path = self.store_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

        self.index = Index(
            chunks=chunks,
            embedder=embedder,
            source_root=meta.get("source_root", ""),
            file_count=meta.get("file_count", len(set(c.file_path for c in chunks))),
        )
        return self.index

    @property
    def is_built(self) -> bool:
        return (self.store_dir / "embedder.pkl").exists()


def _chunk_text(c: CodeChunk) -> str:
    """Build a searchable text representation of a chunk."""
    parts = [c.signature, c.code]
    return "\n".join(parts)
