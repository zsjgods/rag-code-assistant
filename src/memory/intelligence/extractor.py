"""KnowledgeExtractor — extract memories from conversations.

Subscribes to: TASK_END, MESSAGE_THRESHOLD (via TriggerPolicy)

Flow:
  conversation → LLM → MemoryCandidate[] → Validator → Pipeline → MemoryEntry
                                                       ↓
                                              M8 Importance recalculation

LLM is the Proposer, NOT the Authority. Every candidate goes through
Validator → Pipeline → Importance before becoming a MemoryEntry.
"""

from src.memory.intelligence.candidate import ExtractionResult, MemoryCandidate
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.parser import ResponseParser
from src.memory.intelligence.prompt_loader import PromptLoader
from src.memory.intelligence.trigger import TriggerEvent, TriggerPayload
from src.memory.intelligence.validator import CandidateValidator


# Schema for LLM extraction output
EXTRACTION_SCHEMA = {
    "required": ["items"],
    "properties": {
        "items": {"type": "list"},
    },
}

ITEM_SCHEMA = {
    "required": ["type", "text", "summary", "confidence", "source_quote"],
    "properties": {
        "type": {"type": "str"},
        "text": {"type": "str", "max": 5000},
        "summary": {"type": "str", "max": 200},
        "tags": {"type": "list"},
        "estimated_importance": {"type": "float", "min": 0.0, "max": 1.0},
        "confidence": {"type": "float", "min": 0.0, "max": 1.0},
        "reason": {"type": "str", "max": 500},
        "source_quote": {"type": "str", "max": 500},
        "source_message_index": {"type": "int"},
        "candidate_type": {"type": "str"},
    },
}


class KnowledgeExtractor:
    """Extract knowledge from conversation text using LLM.

    Usage:
        extractor = KnowledgeExtractor(
            store=store, pipeline=pipeline,
            llm_call=llm_call, importance_engine=imp_engine,
        )
        extractor.on_trigger(TriggerPayload(event=TriggerEvent.TASK_END))

        # Also usable directly for manual extraction:
        result = extractor.extract(conversation_text)
    """

    def __init__(
        self,
        store,                     # MemoryStore
        pipeline,                  # MemoryPipeline
        llm_call,                  # Callable[[str], str]
        importance_engine=None,    # ImportanceEngine (M8) — for recalculation
        config: IntelligenceConfig | None = None,
    ):
        self._store = store
        self._pipeline = pipeline
        self._llm_call = llm_call
        self._importance_engine = importance_engine
        self._config = config or IntelligenceConfig()

        self._parser = ResponseParser()
        self._validator = CandidateValidator(self._config)
        self._prompts = PromptLoader()

        self._conversation_buffer: list[str] = []

    # ── Trigger handler ───────────────────────────────────────

    def on_trigger(self, payload: TriggerPayload) -> None:
        """Handle a trigger event. Called by AsyncWorker."""
        if not self._config.extraction_enabled:
            return
        if not self._conversation_buffer:
            return

        # Snapshot and clear buffer
        conversation_text = "\n".join(self._conversation_buffer)
        self._conversation_buffer.clear()

        # Extract (may call LLM)
        self.extract(conversation_text)

    # ── Message tracking ──────────────────────────────────────

    def track_message(self, text: str) -> None:
        """Buffer a conversation message for later extraction.

        Called by agent loop after each user/assistant message.
        """
        if text.strip():
            self._conversation_buffer.append(text)

    # ── Extraction ────────────────────────────────────────────

    def extract(self, conversation_text: str) -> ExtractionResult:
        """Extract memories from conversation text.

        Args:
            conversation_text: The full conversation to extract from.

        Returns:
            ExtractionResult with counts of generated/accepted/rejected/created.
        """
        result = ExtractionResult()

        if not conversation_text.strip():
            return result

        # Step 1: LLM extraction
        candidates = self._call_llm_extract(conversation_text)
        result.candidates_generated = len(candidates)

        # Step 2: Validate each candidate
        for candidate in candidates:
            ok, reason = self._validator.validate(candidate, conversation_text)
            if not ok:
                result.candidates_rejected += 1
                result.details.append(f"Rejected: {reason}")
                continue

            result.candidates_accepted += 1

            # Step 3: Convert candidate → MemoryEntry → Pipeline
            entry = self._candidate_to_entry(candidate)
            ok2, reason2, final_entry = self._pipeline.process(entry, self._store)

            if ok2 and final_entry is not None:
                result.entries_created += 1
                result.details.append(
                    f"Created [{final_entry.type.value}] {final_entry.id_str[:8]}.. — {final_entry.content.summary[:80]}"
                )
            else:
                result.candidates_rejected += 1
                result.details.append(f"Pipeline rejected: {reason2}")

        return result

    def _call_llm_extract(self, conversation_text: str) -> list[MemoryCandidate]:
        """Call LLM and parse extraction output."""
        try:
            system_prompt = self._prompts.load("extract_system")
            user_prompt = self._prompts.load(
                "extract_user",
                conversation=conversation_text,
                max_items=str(self._config.extraction_max_per_batch),
            )
            full_prompt = user_prompt
            # Use system prompt as prefix if LLM call supports it
            # For the simple Callable[str, str] convention, combine into one prompt
            combined = f"{system_prompt}\n\n{user_prompt}"
            response = self._llm_call(combined)

            raw = self._parser.parse_json(response)
            if isinstance(raw, dict):
                items = raw.get("items", [raw])
            elif isinstance(raw, list):
                items = raw
            else:
                items = []

            candidates = []
            for item in items[:self._config.extraction_max_per_batch]:
                try:
                    validated = self._parser.validate(item, ITEM_SCHEMA)
                    candidate = self._parser.to_candidate(validated)
                    candidates.append(candidate)
                except Exception:
                    pass  # Skip malformed items

            return candidates
        except Exception:
            return []

    def _candidate_to_entry(self, candidate: MemoryCandidate):
        """Convert a validated MemoryCandidate to a MemoryEntry for Pipeline."""
        from src.memory.types import MemoryEntry, MemoryType, MemoryScope, MemoryVisibility

        mem_type = MemoryType(candidate.type) if candidate.type in {t.value for t in MemoryType} else MemoryType.KNOWLEDGE

        entry = MemoryEntry.create(
            text=candidate.text,
            type=mem_type,
            summary=candidate.summary,
            tags=candidate.tags,
            importance=candidate.estimated_importance,
            confidence=candidate.confidence,
            scope=MemoryScope.PROJECT,
            visibility=MemoryVisibility.PRIVATE,
            source=f"extraction:{candidate.candidate_type}",
            reason=candidate.reason,
            created_by="intelligence_engine",
        )

        # Store extraction metadata
        entry.content.reason = (
            f"[M9 Extraction] confidence={candidate.confidence:.2f} "
            f"quote='{candidate.source_quote[:100]}' — {candidate.reason}"
        )

        return entry

    # ── Stats ─────────────────────────────────────────────────

    @property
    def buffer_size(self) -> int:
        return len(self._conversation_buffer)

    def stats(self) -> dict:
        return {
            "buffer_size": self.buffer_size,
            "enabled": self._config.extraction_enabled,
        }
