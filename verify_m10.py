"""M10 Lifecycle & Operations — End-to-End Verification.

Tests:
  1. State Machine — weighted scoring → state transitions
  2. Archive + Restore — auto-archive + manual restore
  3. Compression — RuleBased strategy
  4. GC — orphan cleanup + broken ref repair
  5. Policy Engine — config-driven thresholds
  6. Metrics — health dashboard
  7. MemoryCore integration — init_lifecycle()
  8. LifecycleWorker — start/stop
"""

import tempfile
import time
from pathlib import Path

from src.memory.events import MemoryEventBus
from src.memory.identity import MemoryID
from src.memory.types import MemoryEntry, MemoryType, MemoryState
from src.memory.store import MemoryStore
from src.memory.lifecycle.config import LifecycleConfig
from src.memory.lifecycle.policy import LifecyclePolicyEngine, StateTransitionPolicy
from src.memory.lifecycle.state import LifecycleStateMachine
from src.memory.lifecycle.archiver import ArchiveEngine
from src.memory.lifecycle.compressor import MemoryCompressor, RuleBasedCompression
from src.memory.lifecycle.gc import GarbageCollector
from src.memory.lifecycle.metrics import LifecycleMetricsCollector, LifecycleMetrics
from src.memory.lifecycle.engine import LifecycleEngine


def _make_store():
    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    return MemoryStore(db_path=tmp)


def test_state_machine():
    """Test weighted scoring and state transitions."""
    print("=" * 60)
    print("Test 1: State Machine")
    print("=" * 60)

    store = _make_store()
    events = store.events
    mgr = store._lifecycle

    # Config with low thresholds so we can see transitions
    config = LifecycleConfig(
        state_warm_threshold=0.80,
        state_cold_threshold=0.50,
        state_archive_threshold=0.20,
    )
    sm = LifecycleStateMachine(store, mgr, events, config)

    # Create entries at different health levels
    healthy = MemoryEntry.create(text="Important", type=MemoryType.DECISION)
    healthy.score.importance = 0.9
    healthy.score.freshness = 0.9
    healthy.score.frequency = 5
    store.create(healthy)

    weak = MemoryEntry.create(text="Old note", type=MemoryType.CONVERSATION)
    weak.score.importance = 0.2
    weak.score.freshness = 0.3
    weak.score.frequency = 0
    store.create(weak)

    very_weak = MemoryEntry.create(text="Very old", type=MemoryType.KNOWLEDGE)
    very_weak.score.importance = 0.05
    very_weak.score.freshness = 0.02
    very_weak.score.frequency = 0
    store.create(very_weak)

    # Evaluate
    counts = sm.evaluate_all()
    print(f"  Transitions: {counts}")

    # Re-read entries
    h = store.read(healthy.id)
    w = store.read(weak.id)
    vw = store.read(very_weak.id)

    print(f"  Healthy: state={h.state.value} (expected: active)")
    print(f"  Weak: state={w.state.value} (expected: cold or warm)")
    print(f"  Very weak: state={vw.state.value if vw else 'ARCHIVED'} (expected: archived)")

    assert h.state == MemoryState.ACTIVE, f"Healthy entry should stay ACTIVE, got {h.state}"
    # Weak should be at least WARM or lower
    assert w.state in (MemoryState.WARM, MemoryState.COLD), f"Weak should be WARM/COLD, got {w.state}"

    # Test single evaluation
    new_state = sm.evaluate_one(healthy)
    print(f"  evaluate_one(healthy): {new_state.value}")
    assert new_state == MemoryState.ACTIVE

    print("\n[PASS] Test 1\n")


def test_archive_restore():
    """Test ArchiveEngine + restore."""
    print("=" * 60)
    print("Test 2: Archive + Restore")
    print("=" * 60)

    store = _make_store()
    events = store.events
    mgr = store._lifecycle

    config = LifecycleConfig(
        archive_enabled=True,
        archive_importance_threshold=0.5,
        archive_min_age_days=0,  # No age requirement for test
    )
    archiver = ArchiveEngine(store, mgr, events, config=config)

    # Create a low-value entry
    entry = MemoryEntry.create(text="Low value", type=MemoryType.CONVERSATION)
    entry.score.importance = 0.1
    entry.score.frequency = 0
    store.create(entry)

    print(f"  Before: active={len(store.get_active())}, archived={len(store.get_archived())}")

    # Archive candidates
    archived = archiver.schedule()
    print(f"  Archived: {archived}")
    assert len(archived) == 1
    assert entry.id.value in archived

    print(f"  After archive: active={len(store.get_active())}, archived={len(store.get_archived())}")

    # Restore
    ok = archiver.restore(entry.id)
    assert ok
    print(f"  After restore: active={len(store.get_active())}, archived={len(store.get_archived())}")
    assert len(store.get_active()) == 1

    restored = store.read(entry.id)
    assert restored.state == MemoryState.ACTIVE

    print("\n[PASS] Test 2\n")


def test_compression():
    """Test RuleBasedCompression."""
    print("=" * 60)
    print("Test 3: Compression (RuleBased)")
    print("=" * 60)

    store = _make_store()
    events = store.events

    config = LifecycleConfig(
        compression_enabled=True,
        compression_strategy="rule",
        compression_min_group_size=2,
    )

    compressor = MemoryCompressor(
        store=store, events=events, config=config
    )

    # Create 3 similar entries
    entries = []
    for i in range(3):
        e = MemoryEntry.create(
            text=f"Python testing tip {i}: Use pytest for testing",
            type=MemoryType.TOOL,
            summary=f"Testing tip {i}",
            tags=["python", "testing"],
        )
        store.create(e)
        entries.append(e)

    print(f"  Before: active={len(store.get_active())}")

    # Compress
    ids = compressor.schedule()
    print(f"  Compressed: {len(ids)} summary entries")
    assert len(ids) >= 1

    # Original entries should be archived
    archived = store.get_archived()
    print(f"  After: active={len(store.get_active())}, archived={len(archived)}")
    assert len(archived) >= 2  # At least 1 of the originals got archived

    print("\n[PASS] Test 3\n")


def test_gc():
    """Test GarbageCollector — orphan cleanup + broken ref repair."""
    print("=" * 60)
    print("Test 4: Garbage Collector")
    print("=" * 60)

    store = _make_store()
    events = store.events

    gc = GarbageCollector(store, events)

    # Create entry A with orphan relations
    entry_a = MemoryEntry.create(text="Entry A", type=MemoryType.KNOWLEDGE)
    entry_a.relation.related["nonexistent_id_1"] = "conflict"
    entry_a.relation.related["nonexistent_id_2"] = "similar"
    store.create(entry_a)

    # Create entry B with orphan parent
    from src.memory.identity import MemoryID
    entry_b = MemoryEntry.create(text="Entry B", type=MemoryType.KNOWLEDGE)
    entry_b.relation.parent = MemoryID("nonexistent_parent")
    store.create(entry_b)

    print(f"  Before GC: A.related={len(entry_a.relation.related)}, B.parent={entry_b.relation.parent}")

    result = gc.collect()
    print(f"  GC result: orphans={result.orphans_cleaned}, broken={result.broken_refs_repaired}")

    # Re-read
    a = store.read(entry_a.id)
    b = store.read(entry_b.id)

    print(f"  After GC: A.related={len(a.relation.related)}, B.parent={b.relation.parent}")
    assert len(a.relation.related) == 0, "Orphan relations should be cleaned"
    assert b.relation.parent is None, "Broken parent ref should be cleared"

    print("\n[PASS] Test 4\n")


def test_policy_engine():
    """Test policy engine configuration."""
    print("=" * 60)
    print("Test 5: Policy Engine")
    print("=" * 60)

    config = LifecycleConfig(
        state_warm_threshold=0.7,
        state_w_importance=0.4,
        state_w_frequency=0.3,
    )
    engine = LifecyclePolicyEngine(config)

    assert engine.state._cfg.state_warm_threshold == 0.7
    assert engine.state._cfg.state_w_importance == 0.4
    print(f"  State policy loaded: warm_threshold={engine.state._cfg.state_warm_threshold}")

    # Hot update
    new_config = LifecycleConfig(state_warm_threshold=0.9)
    engine.update_config(new_config)
    assert engine.state._cfg.state_warm_threshold == 0.9
    print(f"  Hot update: warm_threshold={engine.state._cfg.state_warm_threshold}")

    # Test archive policy
    entry = MemoryEntry.create(text="Test", type=MemoryType.KNOWLEDGE)
    entry.score.importance = 0.1
    should, reason = engine.archive.should_archive(entry, days_since_access=200)
    print(f"  Archive check: should={should}, reason={reason}")
    assert should

    # Test retention policy (disabled by default)
    should2, reason2 = engine.retention.should_purge(entry, days_since_archived=400)
    print(f"  Retention check: should={should2}, reason={reason2}")
    assert not should2  # retention disabled by default

    print("\n[PASS] Test 5\n")


def test_metrics():
    """Test LifecycleMetricsCollector."""
    print("=" * 60)
    print("Test 6: Metrics")
    print("=" * 60)

    store = _make_store()
    collector = LifecycleMetricsCollector(store)

    # Create entries in different states
    for i in range(5):
        e = MemoryEntry.create(text=f"Entry {i}", type=MemoryType.KNOWLEDGE)
        if i < 3:
            e.score.importance = 0.8
        else:
            e.score.importance = 0.3
        store.create(e)
        # Set state after create (store.create forces ACTIVE)
        if i >= 3:
            e.identity.state = MemoryState.WARM

    m = collector.collect()
    print(f"  Active: {m.active_count}, WARM: {m.warm_count}")
    print(f"  Total: {m.total_entries}")
    print(f"  Avg importance: {m.avg_importance:.2f}")
    print(f"  Health score: {m.health_score:.2f}")
    assert m.total_entries >= 5
    assert m.warm_count >= 2

    # Record operations
    collector.record_archive()
    collector.record_cycle()
    m2 = collector.collect()
    assert m2.total_archives == 1
    print(f"  After archive: total_archives={m2.total_archives}")

    print("\n[PASS] Test 6\n")


def test_memorycore_integration():
    """Test MemoryCore.init_lifecycle()."""
    print("=" * 60)
    print("Test 7: MemoryCore integration")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_m10"
    from src.memory import MemoryCore

    core = MemoryCore(db_path=tmp)

    engine = core.init_lifecycle()
    assert engine.is_running
    assert core.lifecycle is engine

    print(f"  init_lifecycle: running={engine.is_running}")

    # Test manual API
    entry = MemoryEntry.create(text="Test", type=MemoryType.KNOWLEDGE)
    core.add(entry)

    # Archive
    ok = engine.archive(entry.id_str)
    print(f"  archive: {ok}")

    # Restore
    ok2 = engine.restore(entry.id_str)
    print(f"  restore: {ok2}")

    # Metrics
    m = engine.metrics()
    print(f"  metrics: total={m.total_entries}")

    engine.stop()
    assert not engine.is_running
    print(f"  stopped: running={engine.is_running}")

    print("\n[PASS] Test 7\n")


def test_worker():
    """Test LifecycleWorker."""
    print("=" * 60)
    print("Test 8: LifecycleWorker")
    print("=" * 60)

    cycles = []
    def cycle_fn():
        cycles.append(time.time())

    config = LifecycleConfig(scheduler_cycle_seconds=1)
    from src.memory.lifecycle.worker import LifecycleWorker
    worker = LifecycleWorker(cycle_fn=cycle_fn, config=config)

    worker.start()
    assert worker.is_running
    time.sleep(1.5)  # Wait for 1 cycle
    worker.stop()

    print(f"  Cycles completed: {len(cycles)}")
    assert len(cycles) >= 1, f"Expected at least 1 cycle, got {len(cycles)}"

    print("\n[PASS] Test 8\n")


if __name__ == "__main__":
    test_state_machine()
    test_archive_restore()
    test_compression()
    test_gc()
    test_policy_engine()
    test_metrics()
    test_memorycore_integration()
    test_worker()
    print("=" * 60)
    print("*** ALL M10 TESTS PASSED ***")
    print("=" * 60)
