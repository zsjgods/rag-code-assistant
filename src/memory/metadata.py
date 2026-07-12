"""Memory Metadata Store — decoupled extension data for MemoryEntry.

Metadata is stored SEPARATELY from MemoryEntry to keep entries lean.
Use cases:
  - Embedding vectors (M7 Retrieval)
  - OCR results
  - Translations
  - Custom plugin data
  - Access logs
  - Audit trail

MetadataStore is a simple key-value store keyed by MemoryID.
It does NOT participate in MemoryStore's CRUD lifecycle — plugins manage
metadata explicitly.
"""

from dataclasses import dataclass, field
from typing import Any

from src.memory.identity import MemoryID


@dataclass
class MemoryMetadata:
    """Decoupled metadata for a single memory entry."""
    entry_id: MemoryID
    data: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def delete(self, key: str) -> bool:
        if key in self.data:
            del self.data[key]
            return True
        return False

    def keys(self) -> list[str]:
        return list(self.data.keys())

    def __contains__(self, key: str) -> bool:
        return key in self.data


class MetadataStore:
    """Independent key-value store for memory metadata.

    Usage:
        mstore = MetadataStore()
        mstore.set(entry_id, "embedding", [0.1, 0.2, ...])
        vec = mstore.get(entry_id, "embedding")  # → [0.1, 0.2, ...]
    """

    def __init__(self):
        self._data: dict[str, MemoryMetadata] = {}  # MemoryID.value → MemoryMetadata

    def get(self, entry_id: MemoryID, key: str, default: Any = None) -> Any:
        """Get a metadata value for an entry."""
        meta = self._data.get(entry_id.value)
        if meta is None:
            return default
        return meta.get(key, default)

    def set(self, entry_id: MemoryID, key: str, value: Any) -> None:
        """Set a metadata value for an entry."""
        meta = self._data.get(entry_id.value)
        if meta is None:
            meta = MemoryMetadata(entry_id=entry_id)
            self._data[entry_id.value] = meta
        meta.set(key, value)

    def get_all(self, entry_id: MemoryID) -> MemoryMetadata | None:
        """Get all metadata for an entry."""
        return self._data.get(entry_id.value)

    def delete(self, entry_id: MemoryID) -> bool:
        """Delete all metadata for an entry. Returns True if existed."""
        return self._data.pop(entry_id.value, None) is not None

    def delete_key(self, entry_id: MemoryID, key: str) -> bool:
        """Delete a specific metadata key for an entry."""
        meta = self._data.get(entry_id.value)
        if meta is None:
            return False
        return meta.delete(key)

    def clear(self) -> None:
        """Remove all metadata."""
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, entry_id: MemoryID) -> bool:
        return entry_id.value in self._data
