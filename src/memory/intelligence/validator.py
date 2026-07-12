"""CandidateValidator — validate MemoryCandidate before Pipeline ingestion.

Checks:
  1. source_quote exists and can be found in source text (fuzzy match)
  2. confidence >= min_confidence
  3. text length in [min, max]
  4. type is a valid MemoryType
  5. summary is non-empty (auto-generate if missing)
"""

import re

from src.memory.intelligence.candidate import MemoryCandidate
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.types import MemoryType


class CandidateValidator:
    """Validate MemoryCandidates before they enter the Pipeline.

    LLM is the Proposer, Validator is the first Gate.
    Only candidates that pass all checks reach the Pipeline.

    Usage:
        validator = CandidateValidator(config)
        ok, reason = validator.validate(candidate, source_text)
        if ok:
            entry = candidate_to_entry(candidate)
            pipeline.process(entry, store)
    """

    def __init__(self, config: IntelligenceConfig | None = None):
        self._config = config or IntelligenceConfig()
        self._valid_types = {t.value for t in MemoryType}

    def validate(
        self,
        candidate: MemoryCandidate,
        source_text: str = "",
    ) -> tuple[bool, str]:
        """Validate a candidate. Returns (accepted, reason).

        Args:
            candidate: The MemoryCandidate from LLM extraction.
            source_text: The original conversation text for source_quote verification.

        Returns:
            (True, "") if accepted, (False, reason) if rejected.
        """
        # 1. Check type validity
        if candidate.type not in self._valid_types:
            return False, f"Invalid type: {candidate.type}"

        # 2. Check text length
        text_len = len(candidate.text)
        if text_len < self._config.extraction_min_text_length:
            return False, f"Text too short: {text_len} < {self._config.extraction_min_text_length}"
        if text_len > self._config.extraction_max_text_length:
            return False, f"Text too long: {text_len} > {self._config.extraction_max_text_length}"

        # 3. Check confidence
        if candidate.confidence < self._config.extraction_min_confidence:
            return False, f"Confidence too low: {candidate.confidence:.2f} < {self._config.extraction_min_confidence}"

        # 4. Check source_quote (hallucination guard)
        if not candidate.source_quote.strip():
            return False, "source_quote is empty — cannot verify origin"
        if source_text:
            ok, reason = self._verify_source_quote(candidate.source_quote, source_text)
            if not ok:
                return False, f"source_quote verification failed: {reason}"

        # 5. Ensure summary exists
        if not candidate.summary.strip():
            candidate.summary = candidate.text[:120].strip()

        return True, ""

    def _verify_source_quote(self, quote: str, source_text: str) -> tuple[bool, str]:
        """Check that source_quote appears in the source text.

        Uses fuzzy matching if configured. This is the key hallucination defense:
        LLM must point to actual words in the conversation, not invent facts.
        """
        if not self._config.validator_source_quote_fuzzy:
            # Exact substring match
            if quote in source_text:
                return True, ""
            return False, f"Quote not found in source text"

        # Fuzzy matching: normalize both, check for substantial overlap
        quote_normalized = self._normalize(quote)
        source_normalized = self._normalize(source_text)

        if len(quote_normalized) < 10:
            # Very short quotes — exact match only
            if quote_normalized in source_normalized:
                return True, ""
            return False, "Short quote not found (fuzzy match requires >= 10 chars)"

        # Split into words and check overlap
        quote_words = set(quote_normalized.split())
        source_words = set(source_normalized.split())

        if not quote_words:
            return False, "Quote has no searchable words"

        overlap = len(quote_words & source_words)
        ratio = overlap / len(quote_words)

        threshold = self._config.validator_source_quote_threshold
        if ratio >= threshold:
            return True, f"Fuzzy match: {ratio:.0%} overlap"

        return False, f"Insufficient overlap: {ratio:.0%} < {threshold:.0%}"

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for fuzzy comparison."""
        # Lowercase, collapse whitespace, remove punctuation
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
