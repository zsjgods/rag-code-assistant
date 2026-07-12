"""AsyncWorker — background thread for M9 LLM calls.

Copies the EmbeddingWorker pattern (M7) exactly:
  - threading.Thread(daemon=True)
  - Queue-based event accumulation → batch processing
  - batch_size + flush_interval triggers
  - max_retries with exponential backoff
  - start() / stop(drain=True) lifecycle

The worker accumulates trigger events and dispatches them to the
appropriate handler (extractor or reflector) in batch.
"""

import queue
import threading
import time
from collections.abc import Callable

from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.trigger import TriggerEvent, TriggerPayload


class AsyncWorker:
    """Background worker for M9 intelligence processing.

    Accumulates trigger events into batches, then calls process_fn(batch).
    This avoids blocking the agent main loop — LLM calls happen in the background.

    Usage:
        worker = AsyncWorker(process_fn=engine.process_batch, config=config)
        worker.start()
        worker.enqueue(TriggerPayload(event=TriggerEvent.TASK_END, ...))
        worker.stop(drain=True)
    """

    def __init__(
        self,
        process_fn: Callable[[list[TriggerPayload]], None],
        config: IntelligenceConfig | None = None,
    ):
        self._config = config or IntelligenceConfig()
        self._process_fn = process_fn

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._failed_count: int = 0

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start the background worker thread."""
        if not self._config.worker_enabled:
            return
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="m9-worker")
        self._thread.start()

    def stop(self, drain: bool = True) -> None:
        """Stop the worker thread.

        Args:
            drain: If True, process remaining items before stopping.
        """
        if not self._running:
            return

        if drain:
            self._drain()

        self._running = False

        # Push sentinel to wake up the thread
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Input ─────────────────────────────────────────────────

    def enqueue(self, payload: TriggerPayload) -> None:
        """Add a trigger event to the processing queue."""
        if not self._running and self._config.worker_enabled:
            # Worker not running — process synchronously
            self._process_fn([payload])
            return

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            pass  # Drop event if queue is full (best-effort)

    # ── Internal ──────────────────────────────────────────────

    def _run(self) -> None:
        """Main worker loop. Accumulates events and flushes in batches."""
        batch: list[TriggerPayload] = []
        last_flush = time.time()
        batch_size = self._config.worker_batch_size
        flush_interval = self._config.worker_flush_interval

        while self._running:
            try:
                # Block with timeout
                item = self._queue.get(timeout=flush_interval)
                if item is None:  # Sentinel — shutdown
                    break
                batch.append(item)
            except queue.Empty:
                pass  # Timeout — check flush conditions

            now = time.time()
            should_flush = (
                len(batch) >= batch_size or
                (batch and (now - last_flush) >= flush_interval)
            )

            if should_flush:
                self._process_batch(batch)
                batch.clear()
                last_flush = now

        # Final drain on exit
        if batch:
            self._process_batch(batch)

    def _process_batch(self, batch: list[TriggerPayload]) -> None:
        """Process a batch with retry logic."""
        if not batch:
            return

        max_retries = self._config.worker_max_retries
        for attempt in range(max_retries):
            try:
                self._process_fn(batch)
                self._failed_count = 0
                return
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    self._failed_count += 1
                    # Last attempt failed — silently drop (best-effort)

    def _drain(self) -> None:
        """Process all remaining items in the queue synchronously."""
        batch: list[TriggerPayload] = []
        while True:
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    batch.append(item)
            except queue.Empty:
                break

        if batch:
            self._process_batch(batch)

    # ── Stats ─────────────────────────────────────────────────

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def stats(self) -> dict:
        return {
            "running": self._running,
            "queue_size": self.queue_size,
            "failed_batches": self._failed_count,
            "batch_size": self._config.worker_batch_size,
            "flush_interval": self._config.worker_flush_interval,
        }
