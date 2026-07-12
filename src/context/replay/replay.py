"""ReplayEngine — rebuild historical prompts from serialized data.

Replay is a DEVELOPMENT DEBUGGING TOOL, not a production recovery mechanism.
It allows developers to:
  - Reconstruct what prompt was sent to the LLM in a past turn
  - Inspect the per-layer breakdown at that point in time
  - Verify that PromptPackage serialization is correct

Usage:
    replay = ReplayEngine(prompt_builder)

    # From a serialized PromptPackage dict
    build_result = replay.from_package_dict(package_data)
    print(build_result.system)
    print(build_result.messages)

    # From an audit log entry
    build_result = replay.from_audit_entry(audit_entry)
"""

from typing import Any

from src.context.prompt_builder import PromptBuilder
from src.context.types import BuildResult
from src.context.serialization import (
    prompt_package_from_dict,
    selection_result_from_dict,
    summary_entry_from_dict,
)
from src.context.layers.summary import SummaryEntry
from src.context.observability.snapshot import DashboardSnapshot


class ReplayEngine:
    """Reconstruct historical prompts from serialized data.

    The engine works with deserialized data only — it does not access
    Store or any live state. All data must be provided as parameters.

    This keeps Replay purely a data transformation tool:
      Serialized dict → PromptPackage → PromptBuilder → BuildResult
    """

    def __init__(self, prompt_builder: PromptBuilder):
        """
        Args:
            prompt_builder: A PromptBuilder instance configured with
                           the same layer structure as the original run.
                           For accurate replay, this MUST be the same
                           instance or an identical clone.
        """
        self._builder = prompt_builder

    # ── From PromptPackage dict ──────────────────────────

    def from_package_dict(self, data: dict) -> BuildResult:
        """Reconstruct a prompt from a serialized PromptPackage dict.

        Args:
            data: A dict with _schema, _type="PromptPackage", and
                  system_parts/message_parts/token_usage fields.

        Returns:
            BuildResult identical to what was produced at pipeline time.
        """
        package = prompt_package_from_dict(data)
        return self._builder.build_from_package(package)

    def package_from_dict(self, data: dict) -> "PromptPackage":
        """Deserialize a PromptPackage from a dict (without building).

        Useful when you want to inspect the package without rendering.
        """
        return prompt_package_from_dict(data)

    # ── From SelectionResult dict ────────────────────────

    def from_selection_result_dict(self, data: dict) -> BuildResult:
        """Reconstruct a prompt from a serialized SelectionResult dict.

        Extracts the package from the result and builds the prompt.

        Args:
            data: A dict with _schema, _type="SelectionResult",
                  and a "package" field.

        Returns:
            BuildResult identical to the original run.
        """
        result = selection_result_from_dict(data)
        return self._builder.build_from_package(result.package)

    # ── From audit entry ─────────────────────────────────

    def from_audit_entry(self, entry: dict) -> BuildResult | None:
        """Reconstruct a prompt from an audit log entry.

        Supports two formats:
          1. With "selection_result_raw": full SelectionResult serialized data
          2. With "dashboard.dashboard": dashboard dict (less precise,
             only token counts, no actual content)

        Args:
            entry: An audit log entry dict.

        Returns:
            BuildResult if the entry contains renderable data, else None.
        """
        # Preferred: full SelectionResult
        raw = entry.get("selection_result_raw")
        if isinstance(raw, dict):
            return self.from_selection_result_dict(raw)

        # Fallback: dashboard (metadata only, no content rebuild)
        dashboard_data = entry.get("dashboard", {})
        if dashboard_data:
            return BuildResult(
                system="",
                messages=[],
                stats=[
                    {"layer_name": k, "token_count": v}
                    for k, v in dashboard_data.get("tokens", {})
                    .get("per_layer", {}).items()
                ],
            )

        return None

    # ── Summary inspection ───────────────────────────────

    @staticmethod
    def summary_entry_from_dict(data: dict) -> SummaryEntry:
        """Deserialize a SummaryEntry from a dict.

        Useful for inspecting saved summary state without a layer instance.
        """
        return summary_entry_from_dict(data)
