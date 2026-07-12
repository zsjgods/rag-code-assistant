"""Candidate — immutable fact reference for context selection.

A Candidate is a PURE REFERENCE, not content. It describes one piece of
context that COULD go into the prompt. Content is fetched on demand via
Collector.resolve(candidate).

Key properties:
  - FROZEN: once created, never modified. Ranker/Policy return new lists.
  - NO PRIORITY: priority is a ranking concern, belongs to PriorityProvider.
  - NO CONTENT: content is fetched via resolve() for lazy loading.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candidate:
    """One piece of candidate context.

    Fields are facts about the content, not decisions (no priority).
    All fields are set at creation and never modified.

    Attributes:
        layer_name:  Source identifier ("instruction", "conversation", etc.)
        item_id:     Unique ID within the source (used by Collector.resolve())
        recency:     Timestamp for recency-based ranking (higher = newer)
        token_count: Estimated token count (available without resolve())
        importance:  0.0–1.0 importance score (from metadata or SummaryEntry)
        metadata:    Free-form dict for extensions (file_path, round_index, etc.)
    """

    layer_name: str
    item_id: str
    recency: float = 0.0
    token_count: int = 0
    importance: float = 0.5
    metadata: dict = field(default_factory=dict, compare=False, hash=False)
