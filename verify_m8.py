"""M8 Importance Engine — End-to-End Verification.

Tests:
  1. Base importance: type_weight × source_weight computed on CREATED
  2. Access tracking: ACCESSED → frequency++, freshness reset, importance boost
  3. Freshness decay: lazy exponential decay formula
  4. Feedback: useful/not_useful/critical
  5. Vacuum detection: low-importance entries emit VACUUMED
  6. Stats: score distribution
"""

import tempfile
import time
from pathlib import Path

from src.memory.events import MemoryEvent, MemoryEventBus
from src.memory.identity import MemoryID
from src.memory.types import MemoryEntry, MemoryType
from src.memory.store import MemoryStore
from src.memory.importance.engine import ImportanceEngine
from src.memory.importance.config import ImportanceConfig


def test_base_importance():
    """Test that CREATED events auto-compute importance from type × source."""
    print("=" * 60)
    print("Test 1: Base Importance (type × source)")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    store = MemoryStore(db_path=tmp)
    events = store.events

    # Create entries with different types and sources
    decision_entry = MemoryEntry.create(
        text="Use PostgreSQL for primary DB",
        type=MemoryType.DECISION,
        source="manual",
        summary="DB decision",
    )
    conversation_entry = MemoryEntry.create(
        text="Discussed caching strategy",
        type=MemoryType.CONVERSATION,
        source="agent",
        summary="Cache discussion",
    )
    # This one has explicit importance — should NOT be overridden
    custom_entry = MemoryEntry.create(
        text="Critical security rule",
        type=MemoryType.DECISION,
        source="manual",
        importance=0.9,
        summary="Security rule",
    )

    store.create(decision_entry)
    store.create(conversation_entry)
    store.create(custom_entry)

    # Start ImportanceEngine (will auto-score existing entries + subscribe to CREATED)
    engine = ImportanceEngine(store, events)
    engine.start()

    # Check auto-scoring
    d = store.read(decision_entry.id)
    c = store.read(conversation_entry.id)
    cu = store.read(custom_entry.id)

    print(f"\nDecision entry:")
    print(f"  Type: {d.type.value}, Source: {d.content.source}")
    print(f"  Importance: {d.importance:.2f} (expected: 0.85 × 1.0 = 0.85)")
    assert abs(d.importance - 0.85) < 0.01, f"Expected 0.85, got {d.importance}"

    print(f"\nConversation entry:")
    print(f"  Type: {c.type.value}, Source: {c.content.source}")
    print(f"  Importance: {c.importance:.2f} (expected: 0.40 × 0.70 = 0.28)")
    assert abs(c.importance - 0.28) < 0.01, f"Expected 0.28, got {c.importance}"

    print(f"\nCustom entry (should NOT be overridden):")
    print(f"  Importance: {cu.importance:.2f} (expected: 0.90 — unchanged)")
    assert abs(cu.importance - 0.90) < 0.01, f"Expected 0.90, got {cu.importance}"

    engine.stop()
    print("\n[PASS] Test 1\n")


def test_access_tracking():
    """Test that ACCESSED events update frequency, freshness, importance."""
    print("=" * 60)
    print("Test 2: Access Tracking")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    store = MemoryStore(db_path=tmp)
    events = store.events
    config = ImportanceConfig()
    config.override_on_create = False  # Don't auto-score for this test

    # Create an entry with known starting values
    entry = MemoryEntry.create(
        text="Pytest is the testing framework",
        type=MemoryType.TOOL,
        source="manual",
        importance=0.5,
    )
    entry.score.frequency = 0
    entry.score.freshness = 1.0
    store.create(entry)

    engine = ImportanceEngine(store, events, config)
    engine.start()

    # Simulate 5 accesses by emitting ACCESSED events
    for i in range(5):
        from src.memory.events import MemoryEventPayload
        events.emit(MemoryEventPayload(
            event=MemoryEvent.ACCESSED,
            entry_id=entry.id_str,
            timestamp=time.time(),
            triggered_by="test",
        ))

    # Re-read entry
    updated = store.read(entry.id)

    print(f"\nAfter 5 accesses:")
    print(f"  Frequency: {updated.frequency} (expected: 5)")
    print(f"  Freshness: {updated.freshness:.2f} (expected: ~1.0 — reset each time)")
    print(f"  Importance: {updated.importance:.4f} (expected: > 0.5 due to boost)")

    assert updated.frequency == 5, f"Expected frequency=5, got {updated.frequency}"
    assert updated.freshness > 0.99, f"Expected freshness≈1.0, got {updated.freshness}"
    assert updated.importance > 0.5, f"Expected importance > 0.5, got {updated.importance}"

    engine.stop()
    print("\n[PASS] Test 2 PASSED\n")


def test_freshness_decay():
    """Test exponential decay formula."""
    print("=" * 60)
    print("Test 3: Freshness Decay")
    print("=" * 60)

    from src.memory.importance.decay import FreshnessDecay
    from src.memory.types import MemoryScore

    config = ImportanceConfig(freshness_half_life_days=30.0, freshness_min=0.01)
    decay = FreshnessDecay(config)

    score = MemoryScore(freshness=1.0)

    # After 30 days: should be ~0.5 (half-life)
    effective = decay.get_effective(score, last_access_ts=time.time() - 30 * 86400)
    print(f"\nAfter 30 days: {effective:.4f} (expected: ~0.50)")
    assert 0.45 < effective < 0.55, f"Expected ~0.50, got {effective}"

    # After 60 days: should be ~0.25
    effective = decay.get_effective(score, last_access_ts=time.time() - 60 * 86400)
    print(f"After 60 days: {effective:.4f} (expected: ~0.25)")
    assert 0.22 < effective < 0.28, f"Expected ~0.25, got {effective}"

    # Floor check: after 365 days, should hit floor
    effective = decay.get_effective(score, last_access_ts=time.time() - 365 * 86400)
    print(f"After 365 days: {effective:.4f} (expected: ~0.01 — floor)")
    assert effective >= 0.01, f"Expected floor ≥ 0.01, got {effective}"

    # Test apply() mutates score
    score2 = MemoryScore(freshness=1.0)
    old_val = score2.freshness
    decay.apply(score2, last_access_ts=time.time() - 30 * 86400)
    assert score2.freshness < old_val, "apply() should mutate freshness"
    print(f"\napply() mutated freshness: 1.00 → {score2.freshness:.4f}")

    print("\n[PASS] Test 3 PASSED\n")


def test_feedback():
    """Test explicit feedback ratings."""
    print("=" * 60)
    print("Test 4: Feedback")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    store = MemoryStore(db_path=tmp)
    events = store.events
    config = ImportanceConfig(override_on_create=False)

    entry = MemoryEntry.create(
        text="Docker compose for local dev",
        type=MemoryType.TOOL,
        source="manual",
        importance=0.6,
        confidence=0.5,
    )
    store.create(entry)

    engine = ImportanceEngine(store, events, config)
    engine.start()

    # Test useful feedback
    result = engine.feedback(entry.id_str, "useful")
    print(f"\nuseful feedback: {result.split(chr(10))[0]}")
    updated = store.read(entry.id)
    print(f"  Confidence: {updated.score.confidence:.2f} (expected: ~0.60)")
    assert updated.score.confidence > 0.55, f"Confidence should increase, got {updated.score.confidence}"

    # Test not_useful feedback
    old_importance = updated.score.importance
    result = engine.feedback(entry.id_str, "not_useful")
    print(f"\nnot_useful feedback: {result.split(chr(10))[0]}")
    updated2 = store.read(entry.id)
    print(f"  Importance: {updated2.score.importance:.2f} (was {old_importance:.2f}, expected lower)")
    assert updated2.score.importance < old_importance, "Importance should decrease"

    # Test critical feedback
    result = engine.feedback(entry.id_str, "critical")
    print(f"\ncritical feedback: {result.split(chr(10))[0]}")
    updated3 = store.read(entry.id)
    print(f"  Importance: {updated3.score.importance:.2f} (expected: ≥ 0.90)")
    assert updated3.score.importance >= 0.90, f"Importance should be ≥ 0.90, got {updated3.score.importance}"

    engine.stop()
    print("\n[PASS] Test 4 PASSED\n")


def test_vacuum_detection():
    """Test that low-importance entries trigger VACUUMED."""
    print("=" * 60)
    print("Test 5: Vacuum Detection")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    store = MemoryStore(db_path=tmp)
    events = store.events
    config = ImportanceConfig(
        override_on_create=False,
        vacuum_enabled=True,
        vacuum_importance_threshold=0.15,
        vacuum_min_age_days=0.0,  # No age requirement for test
        vacuum_auto_archive=False,
    )

    # Create a low-value entry (zero frequency, very low importance, "old")
    stale_entry = MemoryEntry.create(
        text="Temporary note that was never used",
        type=MemoryType.CONVERSATION,
        source="system",
        importance=0.05,
    )
    # Make it "old" by backdating created_at
    stale_entry.identity.created_at = time.time() - 10 * 86400  # 10 days ago
    stale_entry.score.frequency = 0
    store.create(stale_entry)

    # Create a normal entry (should not be vacuumed)
    good_entry = MemoryEntry.create(
        text="Important thing",
        type=MemoryType.DECISION,
        source="manual",
        importance=0.9,
    )
    good_entry.score.frequency = 3
    store.create(good_entry)

    # Track VACUUMED events
    vacuumed_ids = []
    def on_vacuum(payload):
        vacuumed_ids.append(payload.entry_id)

    unsub = events.subscribe(MemoryEvent.VACUUMED, on_vacuum)

    engine = ImportanceEngine(store, events, config)
    engine.start()

    # Manually trigger vacuum check
    vacuumed = engine.vacuum.check()
    print(f"\nVacuumed entries: {vacuumed}")
    print(f"VACUUMED events received: {vacuumed_ids}")

    assert stale_entry.id_str in vacuumed, f"Stale entry should be vacuumed. Got: {vacuumed}"
    assert good_entry.id_str not in vacuumed, f"Good entry should NOT be vacuumed"

    unsub()
    engine.stop()
    print("\n[PASS] Test 5 PASSED\n")


def test_stats():
    """Test that stats() returns score distribution."""
    print("=" * 60)
    print("Test 6: Stats")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_test"
    store = MemoryStore(db_path=tmp)
    events = store.events

    for i in range(5):
        entry = MemoryEntry.create(
            text=f"Test memory {i}",
            type=MemoryType.KNOWLEDGE,
            source="manual",
            importance=0.3 + i * 0.1,
        )
        store.create(entry)

    engine = ImportanceEngine(store, events)
    engine.start()

    stats = engine.stats()
    print(f"\nTotal active: {stats['total_active']}")
    print(f"Distribution: {stats['importance_distribution']}")
    print(f"Tracker: {stats['tracker']}")
    print(f"Feedback: {stats['feedback']}")
    print(f"Vacuum: {stats['vacuum']}")

    assert stats['total_active'] == 5
    assert 'min' in stats['importance_distribution']
    assert stats['running'] is True

    engine.stop()
    print("\n[PASS] Test 6 PASSED\n")


if __name__ == "__main__":
    test_base_importance()
    test_access_tracking()
    test_freshness_decay()
    test_feedback()
    test_vacuum_detection()
    test_stats()
    print("=" * 60)
    print("*** ALL M8 TESTS PASSED")
    print("=" * 60)
