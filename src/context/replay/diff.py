"""SnapshotDiff — compare two DashboardSnapshots side by side.

Given two snapshots (A and B), produces a DiffReport showing:
  - Token changes per layer (+/- tokens, % change)
  - Selection changes (candidates selected/discarded delta)
  - Compression differences (savings delta)
  - Latency differences

Usage:
    diff = SnapshotDiff.compare(snapshot_a, snapshot_b)
    print(diff.summary())
    print(diff.format())
"""

from dataclasses import dataclass, field
from typing import Any

from src.context.observability.snapshot import DashboardSnapshot


# ── Token diff ────────────────────────────────────────────────────────


@dataclass
class TokenLayerDiff:
    """Per-layer token change between two snapshots."""

    layer_name: str
    before: int
    after: int
    delta: int
    percent_change: float  # 0.0 if before == 0


@dataclass
class TokenDiff:
    """Aggregate token changes between two snapshots."""

    total_before: int
    total_after: int
    delta: int
    percent_change: float
    layers: list[TokenLayerDiff] = field(default_factory=list)

    @property
    def increased(self) -> bool:
        return self.delta > 0

    @property
    def decreased(self) -> bool:
        return self.delta < 0


# ── Selection diff ───────────────────────────────────────────────────


@dataclass
class SelectionDiff:
    """Selection pipeline changes between two snapshots."""

    candidates_before: int
    candidates_after: int
    selected_before: int
    selected_after: int
    discarded_before: int
    discarded_after: int
    candidates_delta: int
    selected_delta: int
    discarded_delta: int


# ── Compression diff ─────────────────────────────────────────────────


@dataclass
class CompressionDiff:
    """Compression changes between two snapshots."""

    saved_before: int
    saved_after: int
    saved_delta: int
    percent_before: float
    percent_after: float


# ── Latency diff ─────────────────────────────────────────────────────


@dataclass
class LatencyDiff:
    """Latency changes between two snapshots."""

    total_before_ms: float
    total_after_ms: float
    delta_ms: float


# ── DiffReport (unified output) ──────────────────────────────────────


@dataclass
class DiffReport:
    """Complete diff between two DashboardSnapshots."""

    tokens: TokenDiff = field(default_factory=TokenDiff)
    selection: SelectionDiff = field(default_factory=SelectionDiff)
    compression: CompressionDiff | None = None
    latency: LatencyDiff = field(default_factory=LatencyDiff)
    has_compression: bool = False  # Whether compression data was available

    def summary(self) -> str:
        """One-line summary of the diff."""
        parts = [
            f"tokens: {self.tokens.delta:+d} ({self.tokens.percent_change:+.1%})",
        ]
        if self.selection.candidates_before or self.selection.candidates_after:
            parts.append(
                f"selected: {self.selection.selected_delta:+d}"
            )
        if self.has_compression and self.compression:
            parts.append(
                f"compression saved: {self.compression.saved_delta:+d}"
            )
        parts.append(f"latency: {self.latency.delta_ms:+.1f}ms")
        return " | ".join(parts)

    def format(self, verbose: bool = False) -> str:
        """Multi-line formatted diff output."""
        lines: list[str] = ["=== Snapshot Diff ==="]

        # Token changes
        lines.append(f"Tokens: {self.tokens.total_before} → {self.tokens.total_after} "
                      f"({self.tokens.delta:+d}, {self.tokens.percent_change:+.1%})")
        if verbose:
            for layer in self.tokens.layers:
                if layer.delta != 0:
                    lines.append(
                        f"  {layer.layer_name}: {layer.before} → {layer.after} "
                        f"({layer.delta:+d}, {layer.percent_change:+.1%})"
                    )

        # Selection changes
        lines.append(
            f"Selection: {self.selection.selected_before}/{self.selection.candidates_before} "
            f"→ {self.selection.selected_after}/{self.selection.candidates_after} "
            f"(selected {self.selection.selected_delta:+d}, "
            f"discarded {self.selection.discarded_delta:+d})"
        )

        # Compression changes
        if self.has_compression and self.compression:
            lines.append(
                f"Compression: saved {self.compression.saved_before} "
                f"→ {self.compression.saved_after} "
                f"({self.compression.saved_delta:+d})"
            )

        # Latency changes
        lines.append(
            f"Latency: {self.latency.total_before_ms:.1f}ms "
            f"→ {self.latency.total_after_ms:.1f}ms "
            f"({self.latency.delta_ms:+.1f}ms)"
        )

        return "\n".join(lines)


# ── SnapshotDiff ─────────────────────────────────────────────────────


class SnapshotDiff:
    """Compute diffs between two DashboardSnapshots.

    Usage:
        diff = SnapshotDiff.compare(snapshot_a, snapshot_b)
        print(diff.summary())
    """

    @staticmethod
    def compare(a: DashboardSnapshot, b: DashboardSnapshot) -> DiffReport:
        """Compare two snapshots and produce a DiffReport.

        Args:
            a: Earlier snapshot (baseline).
            b: Later snapshot (comparison).

        Returns:
            DiffReport showing changes from a to b.
        """
        return DiffReport(
            tokens=SnapshotDiff._compare_tokens(a, b),
            selection=SnapshotDiff._compare_selection(a, b),
            compression=SnapshotDiff._compare_compression(a, b),
            latency=SnapshotDiff._compare_latency(a, b),
            has_compression=a.compression is not None or b.compression is not None,
        )

    @staticmethod
    def _compare_tokens(a: DashboardSnapshot, b: DashboardSnapshot) -> TokenDiff:
        layers: list[TokenLayerDiff] = []
        all_keys = set(a.tokens.per_layer.keys()) | set(b.tokens.per_layer.keys())

        for key in sorted(all_keys):
            before = a.tokens.per_layer.get(key, 0)
            after = b.tokens.per_layer.get(key, 0)
            delta = after - before
            pct = (
                delta / before
                if before != 0
                else (float("inf") if after > 0 else 0.0)
            )
            layers.append(TokenLayerDiff(
                layer_name=key,
                before=before,
                after=after,
                delta=delta,
                percent_change=pct,
            ))

        total_delta = b.tokens.total - a.tokens.total
        total_pct = (
            total_delta / a.tokens.total
            if a.tokens.total > 0
            else (float("inf") if b.tokens.total > 0 else 0.0)
        )

        return TokenDiff(
            total_before=a.tokens.total,
            total_after=b.tokens.total,
            delta=total_delta,
            percent_change=total_pct,
            layers=layers,
        )

    @staticmethod
    def _compare_selection(
        a: DashboardSnapshot, b: DashboardSnapshot,
    ) -> SelectionDiff:
        return SelectionDiff(
            candidates_before=a.selection.total_candidates,
            candidates_after=b.selection.total_candidates,
            selected_before=a.selection.selected,
            selected_after=b.selection.selected,
            discarded_before=a.selection.discarded,
            discarded_after=b.selection.discarded,
            candidates_delta=b.selection.total_candidates - a.selection.total_candidates,
            selected_delta=b.selection.selected - a.selection.selected,
            discarded_delta=b.selection.discarded - a.selection.discarded,
        )

    @staticmethod
    def _compare_compression(
        a: DashboardSnapshot, b: DashboardSnapshot,
    ) -> CompressionDiff | None:
        ca = a.compression
        cb = b.compression

        if ca is None and cb is None:
            return None

        return CompressionDiff(
            saved_before=ca.saved_tokens if ca else 0,
            saved_after=cb.saved_tokens if cb else 0,
            saved_delta=(cb.saved_tokens if cb else 0) - (ca.saved_tokens if ca else 0),
            percent_before=ca.saved_percent if ca else 0.0,
            percent_after=cb.saved_percent if cb else 0.0,
        )

    @staticmethod
    def _compare_latency(
        a: DashboardSnapshot, b: DashboardSnapshot,
    ) -> LatencyDiff:
        return LatencyDiff(
            total_before_ms=a.latency.total_ms,
            total_after_ms=b.latency.total_ms,
            delta_ms=b.latency.total_ms - a.latency.total_ms,
        )
