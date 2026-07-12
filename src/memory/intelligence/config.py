"""IntelligenceConfig — all tunable parameters for M9 Intelligence Layer."""

from dataclasses import dataclass, field


@dataclass
class IntelligenceConfig:
    """All tunable parameters for the M9 Intelligence Layer.

    Usage:
        config = IntelligenceConfig()
        config.extraction_min_confidence = 0.6
    """

    # ── Extraction ──
    extraction_enabled: bool = True
    extraction_min_confidence: float = 0.5  # Min LLM confidence for candidate acceptance
    extraction_max_per_batch: int = 5       # Max candidates per extraction batch
    extraction_max_text_length: int = 5000  # Max content text length
    extraction_min_text_length: int = 10    # Min content text length

    # ── Validator ──
    validator_source_quote_fuzzy: bool = True  # Use fuzzy matching for source_quote
    validator_source_quote_threshold: float = 0.6  # Fuzzy match threshold

    # ── Reflection ──
    reflection_enabled: bool = True
    reflection_max_candidates: int = 50       # Top-N entries by importance to consider
    reflection_vector_topk: int = 5           # Top-K similar entries per candidate
    reflection_similarity_threshold: float = 0.75  # Min cosine similarity for pair consideration
    reflection_max_pairs_per_batch: int = 10  # Max LLM calls per reflection batch

    # ── Merge ──
    merge_enabled: bool = True
    merge_similarity_threshold: float = 0.85  # Higher bar for merge (very similar)

    # ── Conflict ──
    conflict_enabled: bool = True
    conflict_similarity_threshold: float = 0.75  # Lower bar for conflict detection

    # ── Refine ──
    refine_enabled: bool = True
    refine_min_importance: float = 0.6        # Only refine entries above this importance
    refine_min_age_days: float = 1.0          # Only refine entries older than this

    # ── Split ──
    split_enabled: bool = True
    split_min_text_length: int = 1000         # Only split entries longer than this

    # ── Trigger ──
    trigger_message_threshold: int = 8         # Emit MESSAGE_THRESHOLD every N messages
    trigger_memory_threshold: int = 5          # Emit MEMORY_THRESHOLD every N new memories
    trigger_idle_seconds: float = 300.0        # Emit IDLE after N seconds of inactivity
    trigger_importance_spike: float = 0.85     # Emit IMPORTANCE_SPIKE when entry > this

    # ── Worker ──
    worker_enabled: bool = True
    worker_batch_size: int = 5                 # Batch size for LLM calls
    worker_flush_interval: float = 2.0         # Seconds between flush checks
    worker_max_retries: int = 3                # Max retries per LLM call
