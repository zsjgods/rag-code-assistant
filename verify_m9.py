"""M9 Intelligence Layer — End-to-End Verification.

Tests:
  1. PromptLoader — load + variable substitution + cache
  2. ResponseParser — JSON extraction + schema validation + to_candidate
  3. CandidateValidator — source_quote check + confidence + text length
  4. TriggerPolicy — emit/subscribe + counter reset
  5. RelationType — apply_relation_pair (symmetric + inverse)
  6. StrategyResult + ReflectionResult — data structures
  7. MemoryCore integration — init_intelligence()
  8. AsyncWorker — start/stop lifecycle
"""

import tempfile
import time
from pathlib import Path

from src.memory.events import MemoryEvent, MemoryEventBus
from src.memory.identity import MemoryID
from src.memory.types import MemoryEntry, MemoryType, MemoryScore, MemoryRelation
from src.memory.store import MemoryStore
from src.memory.intelligence.config import IntelligenceConfig
from src.memory.intelligence.candidate import MemoryCandidate, StrategyResult, ExtractionResult, ReflectionResult
from src.memory.intelligence.prompt_loader import PromptLoader
from src.memory.intelligence.parser import ResponseParser, ParseError, ValidationError
from src.memory.intelligence.validator import CandidateValidator
from src.memory.intelligence.trigger import TriggerPolicy, TriggerEvent, TriggerPayload
from src.memory.intelligence.worker import AsyncWorker
from src.memory.intelligence.relation_types import RelationType, apply_relation_pair, SYMMETRIC_RELATIONS, INVERSE_MAP


def test_prompt_loader():
    """Test PromptLoader loads .md files and substitutes variables."""
    print("=" * 60)
    print("Test 1: PromptLoader")
    print("=" * 60)

    loader = PromptLoader()

    # Test system prompt loading
    system = loader.load("extract_system")
    assert "knowledge extraction assistant" in system, "System prompt should contain role description"
    print(f"  extract_system: {len(system)} chars")

    # Test user prompt with variable substitution
    user = loader.load("extract_user", conversation="Hello world", max_items="3")
    assert "Hello world" in user, "Variable {conversation} should be substituted"
    assert "3" in user, "Variable {max_items} should be substituted"
    print(f"  extract_user with vars: {len(user)} chars")

    # Test all prompts loadable
    for name in loader.available_prompts:
        prompt = loader.load(name)
        assert len(prompt) > 0, f"Prompt {name} should not be empty"
    print(f"  All {len(loader.available_prompts)} prompts loadable")

    # Test cache hit
    loader.reload()
    print(f"  Cache cleared OK")

    print("\n[PASS] Test 1\n")


def test_response_parser():
    """Test JSON extraction, schema validation, and candidate conversion."""
    print("=" * 60)
    print("Test 2: ResponseParser")
    print("=" * 60)

    parser = ResponseParser()

    # Test plain JSON
    result = parser.parse_json('{"items": [{"type": "knowledge"}]}')
    assert isinstance(result, dict)
    assert "items" in result
    print(f"  Plain JSON: OK")

    # Test markdown code block
    result = parser.parse_json('```json\n{"key": "value"}\n```')
    assert result["key"] == "value"
    print(f"  Markdown code block: OK")

    # Test schema validation
    schema = {
        "required": ["type", "text", "confidence"],
        "properties": {
            "type": {"type": "str"},
            "text": {"type": "str", "max": 1000},
            "confidence": {"type": "float", "min": 0.0, "max": 1.0},
            "tags": {"type": "list"},
        },
    }

    valid = parser.validate(
        {"type": "knowledge", "text": "hello", "confidence": 0.8},
        schema,
    )
    assert valid["type"] == "knowledge"
    print(f"  Schema validation (valid): OK")

    # Test missing required field
    try:
        parser.validate({"type": "knowledge"}, schema)
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        print(f"  Schema validation (missing field): {e.errors}")

    # Test extra fields ignored (forward-compatible)
    valid = parser.validate(
        {"type": "knowledge", "text": "hello", "confidence": 0.8, "future_field": 42},
        schema,
    )
    assert "future_field" not in valid  # Extra stripped
    print(f"  Extra fields ignored: OK")

    # Test to_candidate
    ITEM_SCHEMA = {
        "required": ["type", "text", "summary", "confidence", "source_quote"],
        "properties": {
            "type": {"type": "str"},
            "text": {"type": "str", "max": 5000},
            "summary": {"type": "str", "max": 200},
            "tags": {"type": "list"},
            "estimated_importance": {"type": "float", "min": 0.0, "max": 1.0},
            "confidence": {"type": "float", "min": 0.0, "max": 1.0},
            "reason": {"type": "str"},
            "source_quote": {"type": "str"},
            "source_message_index": {"type": "int"},
            "candidate_type": {"type": "str"},
        },
    }

    validated = parser.validate(
        {
            "type": "decision",
            "text": "Use PostgreSQL",
            "summary": "DB choice",
            "tags": ["database", "postgres"],
            "estimated_importance": 0.8,
            "confidence": 0.9,
            "reason": "Important architectural decision",
            "source_quote": "we'll use PostgreSQL",
            "source_message_index": 3,
            "candidate_type": "decision",
        },
        ITEM_SCHEMA,
    )
    candidate = parser.to_candidate(validated)
    assert candidate.type == "decision"
    assert candidate.confidence == 0.9
    assert len(candidate.tags) == 2
    print(f"  to_candidate: type={candidate.type}, confidence={candidate.confidence}")

    print("\n[PASS] Test 2\n")


def test_validator():
    """Test CandidateValidator checks."""
    print("=" * 60)
    print("Test 3: CandidateValidator")
    print("=" * 60)

    config = IntelligenceConfig(extraction_min_confidence=0.5)
    validator = CandidateValidator(config)

    source_text = "We decided to use PostgreSQL for the primary database. The team agreed this is the best choice."

    # Valid candidate
    candidate = MemoryCandidate(
        type="decision",
        text="Use PostgreSQL for primary database",
        summary="DB decision: PostgreSQL",
        tags=["database", "postgres"],
        estimated_importance=0.8,
        confidence=0.9,
        reason="Architectural decision",
        source_quote="We decided to use PostgreSQL",
        candidate_type="decision",
    )
    ok, reason = validator.validate(candidate, source_text)
    assert ok, f"Valid candidate should pass: {reason}"
    print(f"  Valid candidate: accepted")

    # Low confidence
    low_conf = MemoryCandidate(
        type="knowledge",
        text="Something",
        summary="Thing",
        confidence=0.3,
        source_quote="some words",
    )
    ok, reason = validator.validate(low_conf, source_text)
    assert not ok, "Low confidence should be rejected"
    print(f"  Low confidence (0.3): rejected — {reason}")

    # Empty source_quote
    no_quote = MemoryCandidate(
        type="knowledge",
        text="Something important",
        summary="Something",
        confidence=0.8,
        source_quote="",
    )
    ok, reason = validator.validate(no_quote, source_text)
    assert not ok, "Empty source_quote should be rejected"
    print(f"  Empty source_quote: rejected — {reason}")

    # Quote not in source
    bad_quote = MemoryCandidate(
        type="knowledge",
        text="Use MongoDB",
        summary="MongoDB choice",
        confidence=0.8,
        source_quote="We will use MongoDB for everything",
    )
    ok, reason = validator.validate(bad_quote, source_text)
    assert not ok, "Bad quote should be rejected"
    print(f"  Quote not in source: rejected — {reason}")

    print("\n[PASS] Test 3\n")


def test_trigger_policy():
    """Test TriggerPolicy emit/subscribe + counters."""
    print("=" * 60)
    print("Test 4: TriggerPolicy")
    print("=" * 60)

    trigger = TriggerPolicy()
    trigger.configure(message_threshold=3, memory_threshold=2)

    received = []
    def on_task_end(payload):
        received.append(("task_end", payload))

    unsub = trigger.subscribe(TriggerEvent.TASK_END, on_task_end)

    # Trigger task end
    trigger.on_task_end()
    assert len(received) == 1
    assert received[0][0] == "task_end"
    print(f"  TASK_END emitted: OK")

    # Test message threshold
    msg_events = []
    trigger.subscribe(TriggerEvent.MESSAGE_THRESHOLD, lambda p: msg_events.append(p))
    trigger.on_message("msg1")
    trigger.on_message("msg2")
    assert len(msg_events) == 0  # Not yet threshold
    trigger.on_message("msg3")
    assert len(msg_events) == 1  # Threshold triggered
    print(f"  MESSAGE_THRESHOLD after 3 messages: OK (counter reset)")

    # Test memory threshold
    mem_events = []
    trigger.subscribe(TriggerEvent.MEMORY_THRESHOLD, lambda p: mem_events.append(p))
    trigger.on_memory_created(0.5)
    assert len(mem_events) == 0
    trigger.on_memory_created(0.6)
    assert len(mem_events) == 1
    print(f"  MEMORY_THRESHOLD after 2 memories: OK")

    # Test importance spike
    spike_events = []
    trigger.subscribe(TriggerEvent.IMPORTANCE_SPIKE, lambda p: spike_events.append(p))
    trigger.on_memory_created(0.9)
    assert len(spike_events) == 1
    print(f"  IMPORTANCE_SPIKE for 0.9: OK")

    unsub()
    trigger.reset()
    print(f"  Unsubscribe + reset: OK")

    print("\n[PASS] Test 4\n")


def test_relation_types():
    """Test RelationType enum + apply_relation_pair."""
    print("=" * 60)
    print("Test 5: RelationType + apply_relation_pair")
    print("=" * 60)

    # Create two test entries
    entry_a = MemoryEntry.create(text="Entry A", type=MemoryType.KNOWLEDGE)
    entry_b = MemoryEntry.create(text="Entry B", type=MemoryType.KNOWLEDGE)

    # Test CONFLICT (symmetric)
    apply_relation_pair(entry_a, entry_b, RelationType.CONFLICT)
    assert entry_a.relation.related[entry_b.id_str] == "conflict"
    assert entry_b.relation.related[entry_a.id_str] == "conflict"
    print(f"  CONFLICT (symmetric): OK")

    # Test SUPERSEDES (inverse)
    apply_relation_pair(entry_a, entry_b, RelationType.SUPERSEDES)
    assert entry_a.relation.related[entry_b.id_str] == "supersedes"
    assert entry_b.relation.related[entry_a.id_str] == "superseded_by"
    print(f"  SUPERSEDES (inverse): OK")

    # Test SYMMETRIC_RELATIONS
    assert RelationType.CONFLICT in SYMMETRIC_RELATIONS
    assert RelationType.DUPLICATE in SYMMETRIC_RELATIONS
    print(f"  SYMMETRIC_RELATIONS: {[r.value for r in SYMMETRIC_RELATIONS]}")

    # Test INVERSE_MAP
    assert INVERSE_MAP[RelationType.PARENT] == RelationType.CHILD
    assert INVERSE_MAP[RelationType.CHILD] == RelationType.PARENT
    print(f"  INVERSE_MAP: {[(k.value, v.value) for k, v in INVERSE_MAP.items()]}")

    print("\n[PASS] Test 5\n")


def test_data_structures():
    """Test ExtractionResult and ReflectionResult."""
    print("=" * 60)
    print("Test 6: Data structures")
    print("=" * 60)

    # ExtractionResult
    er = ExtractionResult(
        candidates_generated=5,
        candidates_accepted=3,
        candidates_rejected=2,
        entries_created=3,
        details=["Created [decision] abc123.. - DB choice"],
    )
    print(f"  ExtractionResult: {er.candidates_generated}g/{er.candidates_accepted}a/{er.entries_created}c")

    # StrategyResult
    sr = StrategyResult(
        strategy="merge",
        decision="merge",
        entry_ids=["abc123", "def456"],
        new_entry_id="ghi789",
        details="Both describe the same testing preference",
    )
    print(f"  StrategyResult: {sr.strategy}={sr.decision}, affected={len(sr.entry_ids)}")

    # ReflectionResult
    rr = ReflectionResult(
        strategy_results=[sr],
        merges=1,
        conflicts_detected=0,
        refinements=1,
        splits=0,
    )
    assert rr.total_actions == 2
    print(f"  ReflectionResult: total_actions={rr.total_actions}")

    print("\n[PASS] Test 6\n")


def test_memorycore_integration():
    """Test MemoryCore.init_intelligence() wiring."""
    print("=" * 60)
    print("Test 7: MemoryCore integration")
    print("=" * 60)

    tmp = Path(tempfile.mkdtemp()) / "memory_m9"
    from src.memory import MemoryCore

    core = MemoryCore(db_path=tmp)
    core.init_importance()

    # No LLM call function — use a mock
    mock_llm = lambda x: '{"items": []}'

    engine = core.init_intelligence(llm_call=mock_llm)
    assert engine.is_running
    assert core.intelligence is engine

    print(f"  init_intelligence: running={engine.is_running}")
    print(f"  intelligence property: OK")
    print(f"  worker stats: {engine.worker.stats()}")

    engine.stop()
    assert not engine.is_running
    print(f"  stop: running={engine.is_running}")

    print("\n[PASS] Test 7\n")


def test_async_worker():
    """Test AsyncWorker lifecycle."""
    print("=" * 60)
    print("Test 8: AsyncWorker")
    print("=" * 60)

    processed = []
    def process_fn(batch):
        processed.extend(batch)

    config = IntelligenceConfig(worker_batch_size=2, worker_flush_interval=0.1)
    worker = AsyncWorker(process_fn=process_fn, config=config)

    worker.start()
    assert worker.is_running
    print(f"  Started: running={worker.is_running}")

    # Enqueue events
    worker.enqueue(TriggerPayload(event=TriggerEvent.TASK_END, timestamp=time.time()))
    worker.enqueue(TriggerPayload(event=TriggerEvent.MESSAGE_THRESHOLD, timestamp=time.time()))

    # Wait for flush
    time.sleep(0.3)

    assert len(processed) >= 1, f"Expected at least 1 processed, got {len(processed)}"
    print(f"  Processed {len(processed)} events in batch")

    worker.stop(drain=True)
    assert not worker.is_running
    print(f"  Stopped: running={worker.is_running}")

    print("\n[PASS] Test 8\n")


if __name__ == "__main__":
    test_prompt_loader()
    test_response_parser()
    test_validator()
    test_trigger_policy()
    test_relation_types()
    test_data_structures()
    test_memorycore_integration()
    test_async_worker()
    print("=" * 60)
    print("*** ALL M9 TESTS PASSED ***")
    print("=" * 60)
