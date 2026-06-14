"""Error recovery — graded retry with exponential backoff.

Handles: API rate limits, context too long, transient failures.
Each error type has its own recovery strategy.
"""

import time
from typing import Any


class ErrorCategory:
    """Error types and their recovery strategies."""
    RATE_LIMIT = "rate_limit"
    CONTEXT_TOO_LONG = "context_too_long"
    TRANSIENT = "transient"
    FATAL = "fatal"


def categorize_error(error: Exception) -> str:
    """Categorize an error for recovery decision."""
    msg = str(error).lower()

    if "rate" in msg or "429" in msg or "overloaded" in msg:
        return ErrorCategory.RATE_LIMIT
    if "context" in msg and ("long" in msg or "exceed" in msg or "token" in msg):
        return ErrorCategory.CONTEXT_TOO_LONG
    if any(w in msg for w in ("timeout", "connection", "network", "temporary")):
        return ErrorCategory.TRANSIENT

    return ErrorCategory.FATAL


def retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    on_retry=None,
) -> Any:
    """Execute a function with exponential backoff retry.

    Delay: 1s -> 2s -> 4s (capped at max_delay)
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            category = categorize_error(e)

            if category == ErrorCategory.FATAL:
                raise  # Don't retry fatal errors

            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                if on_retry:
                    on_retry(attempt + 1, delay, category, str(e))
                time.sleep(delay)

    raise last_error or RuntimeError("Max retries exceeded")


class ErrorRecoveryPipeline:
    """Graded error recovery — tries lighter fixes before heavier ones."""

    def __init__(self, compression_pipeline=None):
        self.compression = compression_pipeline

    def recover_from_context_error(self, messages: list, error: Exception) -> list:
        """Try to recover from context-too-long by compressing."""
        if self.compression:
            return self.compression.compress(messages)
        return messages  # Can't compress, return as-is

    def should_retry(self, error: Exception) -> bool:
        """Whether an error is worth retrying."""
        cat = categorize_error(error)
        return cat != ErrorCategory.FATAL
