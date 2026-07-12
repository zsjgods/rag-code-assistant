"""Memory Tools — Agent-callable tools for Memory OS.

Registers 7 tools for Agent use:
  - memory_add     — Add a new memory (goes through Pipeline)
  - memory_get     — Read a memory by ID
  - memory_list    — List memories by type/state
  - memory_update  — Update a memory's fields
  - memory_delete  — Soft-delete a memory
  - memory_archive — Archive a memory
  - memory_search  — Keyword search (Phase 1 degraded, replaced by M7 Retrieval)

Returns a list of Tool objects compatible with registry.register_many().
"""

import time

from src.tools.base import build_tool, Tool
from src.memory.identity import MemoryID
from src.memory.types import MemoryEntry, MemoryState, MemoryType, MemoryScope, MemoryVisibility


def build_memory_tools(store, pipeline=None, retrieval_engine=None, importance_engine=None, intelligence_engine=None, lifecycle_engine=None) -> list[Tool]:
    """Build memory tool definitions as Tool objects.

    Args:
        store: MemoryStore instance.
        pipeline: MemoryPipeline instance (optional; used by memory_add).
        retrieval_engine: RetrievalEngine instance (optional; used by memory_search).
        importance_engine: ImportanceEngine instance (optional; used by memory_feedback).
        intelligence_engine: IntelligenceEngine instance (optional; used by M9 tools).
        lifecycle_engine: LifecycleEngine instance (optional; used by M10 tools).

    Returns:
        List of Tool objects ready for registry.register_many().
    """
    return [
        # ── memory_add ─────────────────────────────────────
        build_tool(
            "memory_add",
            (
                "Add a memory to Memory OS. The memory goes through a pipeline "
                "(validate → normalize → deduplicate → policy check) before being stored.\n\n"
                f"Valid types: {[t.value for t in MemoryType]}\n"
                f"Valid scopes: {[s.value for s in MemoryScope]}\n"
                "IMPORTANT: Use this to preserve important knowledge, decisions, "
                "user preferences, and lessons learned across sessions."
            ),
            {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in MemoryType],
                        "description": "Memory type",
                    },
                    "content": {
                        "type": "string",
                        "description": "Memory content (structured markdown recommended)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-line summary (auto-generated if empty)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization and retrieval",
                    },
                    "scope": {
                        "type": "string",
                        "enum": [s.value for s in MemoryScope],
                        "description": "Visibility scope (default: project)",
                    },
                    "importance": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Importance score 0-1 (default: 0.5)",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Confidence in this memory 0-1 (default: 0.5)",
                    },
                    "visibility": {
                        "type": "string",
                        "enum": [v.value for v in MemoryVisibility],
                        "description": "Access level (default: private)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Source identifier (task_id, conversation_id, manual)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this memory is being created",
                    },
                },
                "required": ["type", "content"],
            },
            lambda **kw: _handle_memory_add(store, pipeline, **kw),
        ),

        # ── memory_get ─────────────────────────────────────
        build_tool(
            "memory_get",
            "Read a memory entry by ID.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID"},
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_get(store, **kw),
            is_read_only=True,
            is_concurrency_safe=True,
        ),

        # ── memory_list ────────────────────────────────────
        build_tool(
            "memory_list",
            "List memories, optionally filtered by type or state.",
            {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in MemoryType],
                        "description": "Filter by memory type",
                    },
                    "state": {
                        "type": "string",
                        "enum": [s.value for s in MemoryState],
                        "description": "Filter by state (default: active)",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max entries to return (default: 20)",
                    },
                },
                "required": [],
            },
            lambda **kw: _handle_memory_list(store, **kw),
            is_read_only=True,
            is_concurrency_safe=True,
        ),

        # ── memory_update ──────────────────────────────────
        build_tool(
            "memory_update",
            (
                "Update fields of an existing active memory.\n"
                "Updatable fields: content, summary, tags, importance, confidence.\n"
                "This increments the version number and emits a memory.updated event."
            ),
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID"},
                    "content": {"type": "string", "description": "New content"},
                    "summary": {"type": "string", "description": "New summary"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags"},
                    "importance": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "New importance score",
                    },
                    "confidence": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "New confidence score",
                    },
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_update(store, **kw),
            is_concurrency_safe=True,
        ),

        # ── memory_delete ──────────────────────────────────
        build_tool(
            "memory_delete",
            "Soft-delete a memory (can be recovered).",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID to delete"},
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_delete(store, **kw),
            is_destructive=True,
        ),

        # ── memory_archive ─────────────────────────────────
        build_tool(
            "memory_archive",
            "Archive a memory (won't appear in retrieval, but can be recovered).",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID to archive"},
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_archive(store, **kw),
        ),

        # ── memory_search ──────────────────────────────────
        build_tool(
            "memory_search",
            (
                "Search memories by keywords (Phase 1: simple text matching).\n"
                "Searches content and tags. Returns entries sorted by relevance.\n"
                "NOTE: This will be replaced by semantic search in a future version."
            ),
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for",
                    },
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in MemoryType],
                        "description": "Filter by memory type",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Max results (default: 10)",
                    },
                },
                "required": ["query"],
            },
            lambda **kw: _handle_memory_search(store, retrieval_engine, **kw),
            is_read_only=True,
            is_concurrency_safe=True,
        ),

        # ── memory_feedback ──────────────────────────────────
        build_tool(
            "memory_feedback",
            (
                "Give explicit feedback on a memory's usefulness. This adjusts the memory's "
                "importance, confidence, and success rate scores, which affect future retrieval ranking.\n\n"
                "Ratings:\n"
                "  - useful: The memory was helpful. Boosts confidence and success rate.\n"
                "  - not_useful: The memory was irrelevant or misleading. Lowers importance and confidence.\n"
                "  - critical: This memory is essential knowledge. Sets importance and confidence to high floors.\n\n"
                "Use this when a retrieved memory was particularly helpful (or harmful) to your task."
            ),
            {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Memory ID to give feedback on",
                    },
                    "rating": {
                        "type": "string",
                        "enum": ["useful", "not_useful", "critical"],
                        "description": "How useful was this memory?",
                    },
                },
                "required": ["id", "rating"],
            },
            lambda **kw: _handle_memory_feedback(store, importance_engine, **kw),
        ),

        # ── memory_extract ───────────────────────────────────
        build_tool(
            "memory_extract",
            (
                "Manually trigger knowledge extraction from recent conversation.\n"
                "If conversation_text is provided, extracts from that text. Otherwise "
                "uses the buffered conversation from recent turns.\n"
                "Returns a summary of what was extracted and stored."
            ),
            {
                "type": "object",
                "properties": {
                    "conversation_text": {
                        "type": "string",
                        "description": "Optional: conversation text to extract from. If omitted, uses buffered messages.",
                    },
                },
                "required": [],
            },
            lambda **kw: _handle_memory_extract(intelligence_engine, **kw),
        ),

        # ── memory_reflect ───────────────────────────────────
        build_tool(
            "memory_reflect",
            (
                "Manually trigger memory reflection. Runs all reflection strategies "
                "(merge, conflict detection, refine, split) on the active memory pool.\n"
                "This helps keep the memory store clean and high-quality."
            ),
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
            lambda **kw: _handle_memory_reflect(store, intelligence_engine, **kw),
        ),

        # ── memory_conflicts ──────────────────────────────────
        build_tool(
            "memory_conflicts",
            "List all active memory conflicts (contradictory information pairs).",
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
            lambda **kw: _handle_memory_conflicts(intelligence_engine, **kw),
            is_read_only=True,
            is_concurrency_safe=True,
        ),

        # ── memory_resolve ────────────────────────────────────
        build_tool(
            "memory_resolve",
            (
                "Resolve a memory conflict.\n"
                "Resolutions:\n"
                "  - keep_a: Keep the specified entry, archive conflicting ones\n"
                "  - keep_b: Archive the specified entry, keep conflicting ones\n"
                "  - keep_both: Remove conflict relation, keep all entries"
            ),
            {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Memory ID to resolve conflict for",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["keep_a", "keep_b", "keep_both"],
                        "description": "How to resolve the conflict",
                    },
                },
                "required": ["id", "resolution"],
            },
            lambda **kw: _handle_memory_resolve(store, intelligence_engine, **kw),
        ),

        # ── memory_archive (M10) ──────────────────────────────
        build_tool(
            "memory_archive",
            "Archive a memory entry (move from active to archived pool). Can be restored later.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID to archive"},
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_archive_lifecycle(store, lifecycle_engine, **kw),
        ),

        # ── memory_restore (M10) ──────────────────────────────
        build_tool(
            "memory_restore",
            "Restore an archived memory back to active.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory ID to restore"},
                },
                "required": ["id"],
            },
            lambda **kw: _handle_memory_restore(store, lifecycle_engine, **kw),
        ),

        # ── memory_compress (M10) ─────────────────────────────
        build_tool(
            "memory_compress",
            "Compress similar memories into summary entries. Uses the configured strategy (rule/llm/hybrid).",
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
            lambda **kw: _handle_memory_compress(store, lifecycle_engine, **kw),
        ),

        # ── memory_stats (M10) ────────────────────────────────
        build_tool(
            "memory_stats",
            "Get comprehensive Memory OS health statistics including pool distribution, averages, and operation counts.",
            {
                "type": "object",
                "properties": {},
                "required": [],
            },
            lambda **kw: _handle_memory_stats(lifecycle_engine, **kw),
            is_read_only=True,
            is_concurrency_safe=True,
        ),
    ]


# ═══════════════════════════════════════════════════════════════════
# Tool handlers
# ═══════════════════════════════════════════════════════════════════

def _handle_memory_add(store, pipeline, **kw) -> str:
    """Handle memory_add tool call."""
    mem_type = MemoryType(kw.get("type", "knowledge"))
    content_text = kw.get("content", "")
    summary = kw.get("summary", "")
    tags = kw.get("tags", [])
    scope = MemoryScope(kw.get("scope", "project"))
    importance = float(kw.get("importance", 0.5))
    confidence = float(kw.get("confidence", 0.5))
    visibility = MemoryVisibility(kw.get("visibility", "private"))
    source = kw.get("source", "manual")
    reason = kw.get("reason", "")

    entry = MemoryEntry.create(
        text=content_text,
        type=mem_type,
        summary=summary,
        tags=tags,
        scope=scope,
        importance=importance,
        confidence=confidence,
        visibility=visibility,
        source=source,
        reason=reason,
        created_by="agent",
    )

    if pipeline:
        ok, reason_str, final_entry = pipeline.process(entry, store)
        if not ok:
            return f"Memory rejected: {reason_str}"
        if final_entry and final_entry.id_str != entry.id_str:
            return (
                f"Memory merged with existing entry {final_entry.id_str}\n"
                f"  Type: {final_entry.type.value}\n"
                f"  Frequency: {final_entry.frequency}\n"
                f"  Summary: {final_entry.summary}"
            )
        entry = final_entry

    store.save()

    return (
        f"Memory saved: {entry.id_str}\n"
        f"  Type: {mem_type.value}\n"
        f"  Summary: {entry.summary or content_text[:80]}\n"
        f"  Tags: {', '.join(tags) if tags else '(none)'}"
    )


def _handle_memory_get(store, **kw) -> str:
    """Handle memory_get tool call."""
    entry_id = MemoryID(kw["id"])
    entry = store.read(entry_id)
    if entry is None:
        return f"Memory not found: {kw['id']}"

    return (
        f"Memory: {entry.id_str}\n"
        f"  Type: {entry.type.value}\n"
        f"  State: {entry.state.value}\n"
        f"  Scope: {entry.scope.value}\n"
        f"  Content: {entry.content.text[:500]}\n"
        f"  Summary: {entry.content.summary}\n"
        f"  Tags: {', '.join(entry.content.tags) if entry.content.tags else '(none)'}\n"
        f"  Importance: {entry.importance:.2f} | Confidence: {entry.score.confidence:.2f}\n"
        f"  Frequency: {entry.frequency} | Freshness: {entry.freshness:.2f}\n"
        f"  Version: {entry.version.number}\n"
        f"  Created: {_fmt_time(entry.identity.created_at)}\n"
        f"  Updated: {_fmt_time(entry.version.updated_at)}"
    )


def _handle_memory_list(store, **kw) -> str:
    """Handle memory_list tool call."""
    mem_type = kw.get("type")
    state = kw.get("state", "active")
    limit = int(kw.get("limit", 20))

    if state == "active":
        pool = store.get_active()
    elif state == "archived":
        pool = store.get_archived()
    elif state == "deleted":
        pool = store.get_deleted()
    else:
        return f"Unknown state: {state}"

    entries = list(pool.values())

    if mem_type:
        entries = [e for e in entries if e.type.value == mem_type]

    # Sort by importance desc
    entries.sort(key=lambda e: e.importance, reverse=True)

    if not entries:
        return f"No {state} memories found" + (f" of type {mem_type}" if mem_type else "")

    lines = [f"Memory list ({state}, {len(entries)} total, showing {min(limit, len(entries))}):"]
    for e in entries[:limit]:
        summary = e.content.summary or e.content.text[:80]
        lines.append(
            f"  [{e.type.value}] {e.id_str[:8]}.. "
            f"imp={e.importance:.2f} freq={e.frequency} "
            f"— {summary}"
        )

    return "\n".join(lines)


def _handle_memory_update(store, **kw) -> str:
    """Handle memory_update tool call."""
    entry_id = MemoryID(kw["id"])

    fields = {}
    if "content" in kw:
        fields["content.text"] = kw["content"]
    if "summary" in kw:
        fields["content.summary"] = kw["summary"]
    if "tags" in kw:
        fields["content.tags"] = kw["tags"]
    if "importance" in kw:
        fields["score.importance"] = float(kw["importance"])
    if "confidence" in kw:
        fields["score.confidence"] = float(kw["confidence"])

    if not fields:
        return "No fields to update"

    ok = store.update(entry_id, **fields)
    if not ok:
        return f"Memory not found or no changes: {kw['id']}"

    store.save()
    return f"Memory updated: {kw['id']}\n  Fields: {', '.join(fields.keys())}"


def _handle_memory_delete(store, **kw) -> str:
    """Handle memory_delete tool call."""
    entry_id = MemoryID(kw["id"])
    ok = store.delete(entry_id)
    if not ok:
        return f"Memory not found or not active: {kw['id']}"

    store.save()
    return f"Memory soft-deleted: {kw['id']} (can be recovered)"


def _handle_memory_archive(store, **kw) -> str:
    """Handle memory_archive tool call."""
    entry_id = MemoryID(kw["id"])
    ok = store.archive(entry_id)
    if not ok:
        return f"Memory not found or not active: {kw['id']}"

    store.save()
    return f"Memory archived: {kw['id']} (can be recovered)"


def _handle_memory_search(store, retrieval_engine=None, **kw) -> str:
    """Handle memory_search tool call.

    Phase 2 (M7): Uses RetrievalEngine for semantic + keyword + recent hybrid search.
    Phase 1 fallback: Simple keyword matching.
    """
    query_text = kw.get("query", "")
    mem_type = kw.get("type")
    limit = int(kw.get("limit", 10))

    if not query_text:
        return "Please provide a search query"

    # ── Phase 2: Hybrid semantic search ──
    if retrieval_engine is not None:
        try:
            from src.memory.retrieval.query import RetrievalQuery
            rq = RetrievalQuery(
                text=query_text,
                type_filter=[mem_type] if mem_type else None,
                max_results=limit,
            )
            results = retrieval_engine.retrieve(rq)

            if not results:
                return f"No memories found matching: {query_text}"

            lines = [f"Memory search results for '{query_text}' ({len(results)} found, hybrid):"]
            for r in results[:limit]:
                entry = r.entry
                if entry is None:
                    entry = store.read(MemoryID(r.id))
                if entry is None:
                    continue
                summary = entry.content.summary or entry.content.text[:100]
                lines.append(
                    f"  [{entry.type.value}] {entry.id_str[:8]}.. "
                    f"score={r.final_score:.2f} (src={r.source}) — {summary}"
                )
            return "\n".join(lines)
        except Exception:
            pass  # Fall through to Phase 1

    # ── Phase 1: Keyword fallback ──
    query_lower = query_text.lower()
    keywords = query_lower.split()
    results: list[tuple[float, object]] = []

    for entry in store.get_active().values():
        if mem_type and entry.type.value != mem_type:
            continue

        content_lower = entry.content.text.lower()
        summary_lower = entry.content.summary.lower()
        tags_lower = [t.lower() for t in entry.content.tags]

        score = 0.0
        for kw in keywords:
            score += content_lower.count(kw) * 1.0
            score += summary_lower.count(kw) * 3.0
            if any(kw in t for t in tags_lower):
                score += 5.0

        if score > 0:
            score *= (0.5 + entry.importance * 0.5)
            results.append((score, entry))

    results.sort(key=lambda x: x[0], reverse=True)

    if not results:
        return f"No memories found matching: {query_text}"

    lines = [f"Memory search results for '{query_text}' ({len(results)} found, keyword):"]
    for score, entry in results[:limit]:
        summary = entry.content.summary or entry.content.text[:100]
        lines.append(
            f"  [{entry.type.value}] {entry.id_str[:8]}.. "
            f"score={score:.1f} — {summary}"
        )

    return "\n".join(lines)


def _handle_memory_feedback(store, importance_engine=None, **kw) -> str:
    """Handle memory_feedback tool call."""
    entry_id = kw.get("id", "")
    rating = kw.get("rating", "")

    if not entry_id:
        return "Missing memory ID"

    if importance_engine is not None:
        result = importance_engine.feedback(entry_id, rating)
        store.save()
        return result
    else:
        # Fallback: manually adjust score fields
        entry = store.read(MemoryID(entry_id))
        if entry is None:
            return f"Memory not found: {entry_id}"

        if rating == "useful":
            entry.score.confidence = min(1.0, entry.score.confidence + 0.1)
            entry.score.importance = min(1.0, entry.score.importance + 0.02)
        elif rating == "not_useful":
            entry.score.confidence = max(0.0, entry.score.confidence - 0.1)
            entry.score.importance = max(0.0, entry.score.importance - 0.1)
        elif rating == "critical":
            entry.score.importance = max(entry.score.importance, 0.9)
            entry.score.confidence = max(entry.score.confidence, 0.9)
        else:
            return f"Unknown rating: {rating}"

        store.save()
        return (
            f"Feedback recorded: {rating}\n"
            f"  Importance: {entry.score.importance:.2f}\n"
            f"  Confidence: {entry.score.confidence:.2f}"
        )


def _handle_memory_extract(intelligence_engine=None, **kw) -> str:
    """Handle memory_extract tool call."""
    if intelligence_engine is None:
        return "IntelligenceEngine not configured. Call core.init_intelligence() first."

    conversation_text = kw.get("conversation_text", "")
    if conversation_text:
        result = intelligence_engine.extract_now(conversation_text)
    else:
        result = intelligence_engine.extract_now()

    if result is None:
        return "No conversation text available for extraction."

    return (
        f"Extraction complete:\n"
        f"  Candidates generated: {result.candidates_generated}\n"
        f"  Accepted: {result.candidates_accepted}\n"
        f"  Rejected: {result.candidates_rejected}\n"
        f"  Entries created: {result.entries_created}\n"
        + ("\nDetails:\n" + "\n".join(f"  - {d}" for d in result.details) if result.details else "")
    )


def _handle_memory_reflect(store, intelligence_engine=None, **kw) -> str:
    """Handle memory_reflect tool call."""
    if intelligence_engine is None:
        return "IntelligenceEngine not configured. Call core.init_intelligence() first."

    result = intelligence_engine.reflect_now()
    store.save()

    return (
        f"Reflection complete:\n"
        f"  Merges: {result.merges}\n"
        f"  Conflicts detected: {result.conflicts_detected}\n"
        f"  Refinements: {result.refinements}\n"
        f"  Splits: {result.splits}\n"
        f"  Supersedes: {result.supersedes}\n"
        f"  Total actions: {result.total_actions}"
    )


def _handle_memory_conflicts(intelligence_engine=None, **kw) -> str:
    """Handle memory_conflicts tool call."""
    if intelligence_engine is None:
        return "IntelligenceEngine not configured. Call core.init_intelligence() first."

    conflicts = intelligence_engine.list_conflicts()
    if not conflicts:
        return "No active memory conflicts found."

    lines = [f"Active conflicts ({len(conflicts)}):"]
    for c in conflicts:
        lines.append(
            f"  [{c['entry_a'][:8]}..] {c['summary_a'][:60]}\n"
            f"    vs [{c['entry_b'][:8]}..] {c['summary_b'][:60]}\n"
        )
    return "\n".join(lines)


def _handle_memory_resolve(store, intelligence_engine=None, **kw) -> str:
    """Handle memory_resolve tool call."""
    if intelligence_engine is None:
        return "IntelligenceEngine not configured. Call core.init_intelligence() first."

    entry_id = kw.get("id", "")
    resolution = kw.get("resolution", "keep_both")
    result = intelligence_engine.resolve_conflict(entry_id, resolution)
    store.save()
    return result


def _handle_memory_archive_lifecycle(store, lifecycle_engine=None, **kw) -> str:
    """Handle memory_archive tool call (M10)."""
    entry_id = kw.get("id", "")
    if lifecycle_engine is not None:
        ok = lifecycle_engine.archive(entry_id)
        if ok:
            store.save()
            return f"Memory archived: {entry_id}"
        return f"Failed to archive: {entry_id} (not found or not in active pool)"
    else:
        # Fallback: use store directly
        from src.memory.identity import MemoryID
        ok = store.archive(MemoryID(entry_id))
        if ok:
            store.save()
            return f"Memory archived: {entry_id}"
        return f"Failed to archive: {entry_id}"


def _handle_memory_restore(store, lifecycle_engine=None, **kw) -> str:
    """Handle memory_restore tool call (M10)."""
    entry_id = kw.get("id", "")
    if lifecycle_engine is not None:
        ok = lifecycle_engine.restore(entry_id)
        if ok:
            store.save()
            return f"Memory restored: {entry_id}"
        return f"Failed to restore: {entry_id}"
    else:
        from src.memory.identity import MemoryID
        ok = store.recover(MemoryID(entry_id))
        if ok:
            store.save()
            return f"Memory restored: {entry_id}"
        return f"Failed to restore: {entry_id}"


def _handle_memory_compress(store, lifecycle_engine=None, **kw) -> str:
    """Handle memory_compress tool call (M10)."""
    if lifecycle_engine is None:
        return "LifecycleEngine not configured. Call core.init_lifecycle() first."

    ids = lifecycle_engine.compress_now()
    store.save()
    return f"Compression complete: {len(ids)} summary entries created\n  IDs: {', '.join(i[:8]+'..' for i in ids)}" if ids else "No compressible groups found."


def _handle_memory_stats(lifecycle_engine=None, **kw) -> str:
    """Handle memory_stats tool call (M10)."""
    if lifecycle_engine is None:
        return "LifecycleEngine not configured. Call core.init_lifecycle() first."

    m = lifecycle_engine.metrics()
    return (
        f"Memory OS Health:\n"
        f"  Pool: ACTIVE={m.active_count} WARM={m.warm_count} COLD={m.cold_count} ARCHIVED={m.archived_count} DELETED={m.deleted_count}\n"
        f"  Total: {m.total_entries}\n"
        f"  Avg Importance: {m.avg_importance:.2f}\n"
        f"  Avg Freshness: {m.avg_freshness:.2f}\n"
        f"  Avg Frequency: {m.avg_frequency:.1f}\n"
        f"  Health Score: {m.health_score:.2f}\n"
        f"  Archives: {m.total_archives} | Restores: {m.total_restores} | Compressions: {m.total_compressions}\n"
        f"  Merges: {m.total_merges} | Conflicts: {m.total_conflicts}\n"
        f"  Orphans Cleaned: {m.orphans_cleaned} | Broken Repaired: {m.broken_refs_repaired}"
    )


def _fmt_time(ts: float) -> str:
    """Format a timestamp as ISO datetime string."""
    if ts <= 0:
        return "never"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
