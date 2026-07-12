"""Circuit Breaker for the CompressionPipeline.

Prevents the pipeline from repeatedly calling expensive LLM compression
when it is failing consecutively. Three-state machine:

    CLOSED  → normal operation, requests pass through
    OPEN    → fused, all requests rejected immediately
    HALF_OPEN → trial state after timeout, allows one request

After a successful trial the breaker resets to CLOSED.
After a failure in HALF_OPEN it returns to OPEN with a fresh timeout.
"""

import time
from enum import Enum


class CircuitBreakerState(Enum):
    CLOSED = "closed"          # Normal — let requests through
    OPEN = "open"              # Fused — reject immediately
    HALF_OPEN = "half_open"    # Trial — allow one request


class CircuitBreaker:
    """Three-state circuit breaker with automatic half-open recovery.

    Usage:
        breaker = CircuitBreaker(max_failures=3, reset_timeout=60.0)

        if not breaker.is_open:
            try:
                result = expensive_call()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
        else:
            # Circuit is open — skip or degrade gracefully
            result = fallback()
    """

    def __init__(self, max_failures: int = 3, reset_timeout: float = 60.0):
        """
        Args:
            max_failures: Consecutive failures before opening the circuit.
            reset_timeout: Seconds before transitioning from OPEN → HALF_OPEN.
        """
        if max_failures < 1:
            raise ValueError("max_failures must be >= 1")
        if reset_timeout <= 0:
            raise ValueError("reset_timeout must be > 0")

        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self._failures: int = 0
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._last_failure_time: float = 0.0
        self._total_failures: int = 0  # lifetime counter for observability

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        """True when the circuit is open (fused) — don't attempt the operation.

        Automatically transitions from OPEN → HALF_OPEN after reset_timeout.
        """
        if self._state is CircuitBreakerState.HALF_OPEN:
            return False  # Allow a trial

        if self._state is CircuitBreakerState.OPEN:
            if time.time() - self._last_failure_time >= self.reset_timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                return False  # Allow trial
            return True  # Still fused

        return False  # CLOSED — normal

    def record_success(self) -> None:
        """Call after a successful operation. Resets failure count and state."""
        self._failures = 0
        self._state = CircuitBreakerState.CLOSED

    def record_failure(self) -> None:
        """Call after a failed operation. May transition to OPEN."""
        self._failures += 1
        self._last_failure_time = time.time()
        self._total_failures += 1

        if self._state is CircuitBreakerState.HALF_OPEN:
            # Trial failed — back to open with a fresh timeout
            self._state = CircuitBreakerState.OPEN
        elif self._failures >= self.max_failures:
            self._state = CircuitBreakerState.OPEN

    def reset(self) -> None:
        """Manually reset to closed state. Useful for /compact force."""
        self._failures = 0
        self._state = CircuitBreakerState.CLOSED
        self._last_failure_time = 0.0

    # ── Observability ──────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitBreakerState:
        """Current breaker state."""
        return self._state

    @property
    def failures(self) -> int:
        """Current consecutive failure count."""
        return self._failures

    @property
    def total_failures(self) -> int:
        """Lifetime failure count (never resets)."""
        return self._total_failures

    @property
    def remaining_attempts(self) -> int:
        """Number of failures before the circuit opens (CLOSED only)."""
        if self._state is not CircuitBreakerState.CLOSED:
            return 0
        return max(0, self.max_failures - self._failures)

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self._state.value}, "
            f"failures={self._failures}/{self.max_failures}, "
            f"total={self._total_failures}, "
            f"timeout={self.reset_timeout}s)"
        )
