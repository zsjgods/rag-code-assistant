"""Collector — abstract interface for extracting Candidates from Layers.

Two responsibilities:
  collect(ctx)  → scan Layer data, return Candidate references (no content)
  resolve(cand) → lazy-fetch content for a specific Candidate

Layer is NEVER modified by a Collector. The relationship is read-only.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.context.selection.candidate import Candidate

if TYPE_CHECKING:
    from src.context.layers.instruction import InstructionLayer
    from src.context.layers.conversation import ConversationLayer
    from src.context.layers.workspace import WorkspaceLayer
    from src.context.layers.file_cache import FileCacheLayer
    from src.context.layers.summary import SummaryLayer
    from src.context.layers.base import BaseLayer  # for MemoryLayer typing


@dataclass
class SelectionContext:
    """Pipeline input — lightweight wrapper around active Layer instances.

    All fields are optional (M1-only mode passes instruction + conversation).
    New layers are added here, not to the pipeline interface.
    """

    instruction: "InstructionLayer | None" = None
    conversation: "ConversationLayer | None" = None
    workspace: "WorkspaceLayer | None" = None
    file_cache: "FileCacheLayer | None" = None
    summary: "SummaryLayer | None" = None
    memory: "BaseLayer | None" = None  # M6: MemoryLayer


class Collector(ABC):
    """Extracts Candidates from a Layer.

    Subclasses MUST set source_name to the matching Layer name.

    Example:
        class ConversationCollector(Collector):
            source_name = "conversation"
    """

    source_name: str = ""

    @abstractmethod
    def collect(self, ctx: SelectionContext) -> list[Candidate]:
        """Scan the layer and return Candidate references.

        Called once per pipeline run. Should be fast — no I/O, no LLM.
        Content is resolved lazily via resolve().
        """
        ...

    @abstractmethod
    def resolve(self, candidate: Candidate, ctx: SelectionContext) -> str | list[dict]:
        """Fetch the actual content for a Candidate.

        Called during the pack phase, only for selected candidates.
        The SelectionContext is provided so the collector can access the
        correct layer and render the content for this candidate.

        Must return render()-compatible format (str for system, list for messages).
        """
        ...
