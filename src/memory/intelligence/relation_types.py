"""RelationType — extensible enum for memory graph relationships.

M9 defines the base set. Future milestones (M10 Knowledge Graph, M11 Evolution)
add new types without schema changes.

Stored in MemoryRelation.related: dict[str, str]
Key: MemoryID.value of the target entry
Value: RelationType value string
"""

from enum import StrEnum


class RelationType(StrEnum):
    """Memory relationship types — extensible by design."""

    # ── Structure (M6) ──
    PARENT = "parent"              # This entry is the parent (source of a split)
    CHILD = "child"                # This entry is a child (result of a split)

    # ── Similarity (M9) ──
    DUPLICATE = "duplicate"        # Near-identical → candidate for merge
    SIMILAR = "similar"            # Semantically close but not duplicate

    # ── Evolution (M9) ──
    SUPERSEDES = "supersedes"      # This entry supersedes (replaces) the target
    SUPERSEDED_BY = "superseded_by"  # This entry is superseded by the target
    DERIVED_FROM = "derived_from"  # This entry was derived/refined from the target

    # ── Conflict (M9) ──
    CONFLICT = "conflict"          # Contradictory — both valid in different contexts

    # ── Reference (M9) ──
    REFERENCES = "references"      # Cites or relates to target without contradiction


# ── Relation semantics ──

# Relations that are symmetric (applied to both sides)
SYMMETRIC_RELATIONS = {
    RelationType.DUPLICATE,
    RelationType.SIMILAR,
    RelationType.CONFLICT,
}

# Relations that imply an inverse on the target
INVERSE_MAP: dict[RelationType, RelationType] = {
    RelationType.PARENT: RelationType.CHILD,
    RelationType.CHILD: RelationType.PARENT,
    RelationType.SUPERSEDES: RelationType.SUPERSEDED_BY,
    RelationType.SUPERSEDED_BY: RelationType.SUPERSEDES,
}


def apply_relation_pair(
    entry_a,   # MemoryEntry
    entry_b,   # MemoryEntry
    rel_type: RelationType,
) -> None:
    """Apply a relation to both entries, handling symmetry and inverses."""
    from src.memory.identity import MemoryID

    target_b = MemoryID(entry_b.id_str) if not isinstance(entry_b.id, MemoryID) else entry_b.id
    target_a = MemoryID(entry_a.id_str) if not isinstance(entry_a.id, MemoryID) else entry_a.id

    if rel_type in SYMMETRIC_RELATIONS:
        # Same relation on both sides
        entry_a.relation.add_relation(target_b, rel_type.value)
        entry_b.relation.add_relation(target_a, rel_type.value)
    elif rel_type in INVERSE_MAP:
        # Apply forward and inverse
        inverse = INVERSE_MAP[rel_type]
        entry_a.relation.add_relation(target_b, rel_type.value)
        entry_b.relation.add_relation(target_a, inverse.value)
    else:
        # One-way (e.g., REFERENCES)
        entry_a.relation.add_relation(target_b, rel_type.value)
