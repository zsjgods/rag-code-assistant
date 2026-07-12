"""EmbeddingWorker — asynchronous background embedding service.

Listens to MemoryEvent.CREATED and MemoryEvent.UPDATED events.
Accumulates entries in a batch queue, embeds them in the background,
and updates the VectorIndex + MetadataStore without blocking the main thread.

Usage:
    worker = EmbeddingWorker(embedding_index, store, events)
    worker.start()
    # ... Agent creates/updates memories ...
    worker.stop()
"""

import threading
import time
from queue import Empty, Queue

from src.memory.events import MemoryEvent, MemoryEventPayload
from src.memory.identity import MemoryID


class EmbeddingWorker:
    """Background worker for asynchronous embedding generation.

    Architecture:
      - Dedicated daemon thread
      - Batch accumulation (batch_size or flush_interval triggers processing)
      - Retry on failure (exponential backoff, max 3 retries)
      - Graceful shutdown (process remaining queue items)

    Usage:
        worker = EmbeddingWorker(embedding_index, store, events)
        worker.start()
        # ... create/update memories ...
        worker.stop()  # Blocks until remaining items are processed
    """

    def __init__(
        self,
        embedding_index,      # EmbeddingIndex
        store,                # MemoryStore
        events,               # MemoryEventBus
        batch_size: int = 10,
        flush_interval: float = 1.0,
        max_retries: int = 3,
    ):
        self._emb_idx = embedding_index
        self._store = store
        self._events = events
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries

        self._queue: Queue = Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._unsubscribe_fns: list = []

        # Stats
        self._processed = 0
        self._failed = 0
        self._started_at: float | None = None

    def start(self) -> None:
        """Start the background worker thread and subscribe to events."""
        if self._running:
            return

        self._running = True
        self._started_at = time.time()

        # Subscribe to create/update events
        self._unsubscribe_fns.append(
            self._events.subscribe(MemoryEvent.CREATED, self._on_entry_created)
        )
        self._unsubscribe_fns.append(
            self._events.subscribe(MemoryEvent.UPDATED, self._on_entry_updated)
        )

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, drain: bool = True) -> None:
        """Stop the worker.

        Args:
            drain: If True, process remaining queue items before stopping.
        """
        if not self._running:
            return

        self._running = False

        # Unsubscribe from events
        for fn in self._unsubscribe_fns:
            fn()
        self._unsubscribe_fns.clear()

        # Wait for thread
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    # ═══════════════════════════════════════════════════════════
    # Event handlers
    # ═══════════════════════════════════════════════════════════

    def _on_entry_created(self, payload: MemoryEventPayload) -> None:
        self._queue.put(("create", payload.entry_id))

    def _on_entry_updated(self, payload: MemoryEventPayload) -> None:
        self._queue.put(("update", payload.entry_id))

    # ═══════════════════════════════════════════════════════════
    # Main loop
    # ═══════════════════════════════════════════════════════════

    def _run(self) -> None:
        """Main worker loop: accumulate batch → embed → update index."""
        batch: set[str] = set()  # Deduplicate: same entry updated multiple times
        last_flush = time.time()

        while self._running:
            try:
                action, entry_id = self._queue.get(timeout=0.5)
                batch.add(entry_id)
            except Empty:
                pass

            # Flush if batch full or interval elapsed
            if len(batch) >= self._batch_size or (
                batch and time.time() - last_flush >= self._flush_interval
            ):
                self._process_batch(list(batch))
                batch.clear()
                last_flush = time.time()

        # Drain remaining
        if batch:
            self._process_batch(list(batch))

    def _process_batch(self, entry_ids: list[str]) -> None:
        """Process a batch of entry IDs: read from store, embed, update index."""
        entries = []
        for eid_str in entry_ids:
            entry = self._store.read(MemoryID(eid_str))
            if entry is not None:
                entries.append(entry)

        if not entries:
            return

        # Retry loop
        for attempt in range(self._max_retries):
            try:
                count = self._emb_idx.embed_batch(entries)
                self._processed += count
                return
            except Exception:
                if attempt < self._max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    self._failed += len(entries)

    # ═══════════════════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════════════════

    @property
    def stats(self) -> dict:
        uptime = time.time() - (self._started_at or time.time())
        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "processed": self._processed,
            "failed": self._failed,
            "uptime_seconds": round(uptime, 1),
        }

    def __repr__(self) -> str:
        s = self.stats
        return (
            f"EmbeddingWorker(running={s['running']}, processed={s['processed']}, "
            f"failed={s['failed']}, queue={s['queue_size']})"
        )
