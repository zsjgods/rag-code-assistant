"""LifecycleWorker — background thread for M10 lifecycle operations.

Same pattern as M7 EmbeddingWorker and M9 AsyncWorker:
  - threading.Thread(daemon=True)
  - Periodic cycle execution via scheduler
  - start() / stop() lifecycle
  - max_retries with exponential backoff
"""

import threading
import time
from collections.abc import Callable

from src.memory.lifecycle.config import LifecycleConfig


class LifecycleWorker:
    """Background worker for periodic lifecycle operations.

    Usage:
        worker = LifecycleWorker(cycle_fn=engine.run_cycle, config=config)
        worker.start()
        worker.stop()
    """

    def __init__(
        self,
        cycle_fn: Callable[[], None],
        config: LifecycleConfig | None = None,
    ):
        self._config = config or LifecycleConfig()
        self._cycle_fn = cycle_fn

        self._running = False
        self._thread: threading.Thread | None = None
        self._failed_cycles: int = 0
        self._cycles_completed: int = 0

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start the background worker thread."""
        if not self._config.scheduler_enabled:
            return
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="m10-lifecycle-worker"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker thread."""
        if not self._running:
            return

        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Internal ──────────────────────────────────────────────

    def _run(self) -> None:
        """Main worker loop. Runs the cycle function every N seconds."""
        cycle_seconds = self._config.scheduler_cycle_seconds
        max_retries = self._config.scheduler_worker_max_retries

        while self._running:
            try:
                self._cycle_fn()
                self._cycles_completed += 1
                self._failed_cycles = 0
            except Exception:
                self._failed_cycles += 1

            # Sleep between cycles, checking running flag
            for _ in range(int(cycle_seconds)):
                if not self._running:
                    break
                time.sleep(1.0)

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "running": self._running,
            "cycles_completed": self._cycles_completed,
            "failed_cycles": self._failed_cycles,
            "cycle_seconds": self._config.scheduler_cycle_seconds,
        }
