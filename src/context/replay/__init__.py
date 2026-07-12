"""Replay — historical prompt reconstruction and snapshot diffing.

Replay is a DEVELOPMENT DEBUGGING TOOL, not a production mechanism.

Two subsystems:
  ReplayEngine — rebuilds prompts from serialized PromptPackage or
                 SelectionResult data via PromptBuilder.
  SnapshotDiff — compares two DashboardSnapshots and reports changes
                 in token counts, selection, compression, and latency.

Usage:
    replay = ReplayEngine(prompt_builder)
    result = replay.from_package_dict(serialized_package)
    print(result.system)

    diff = SnapshotDiff.compare(snapshot_a, snapshot_b)
    print(diff.summary())
"""

from src.context.replay.replay import ReplayEngine
from src.context.replay.diff import (
    SnapshotDiff,
    DiffReport,
    TokenDiff,
    TokenLayerDiff,
    SelectionDiff,
    CompressionDiff,
    LatencyDiff,
)

__all__ = [
    "ReplayEngine",
    "SnapshotDiff",
    "DiffReport",
    "TokenDiff",
    "TokenLayerDiff",
    "SelectionDiff",
    "CompressionDiff",
    "LatencyDiff",
]
