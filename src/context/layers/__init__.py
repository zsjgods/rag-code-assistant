"""Context Layers — self-contained sources of prompt content.

Each layer manages one category of context and exposes a uniform render() interface.
"""

from src.context.layers.base import BaseLayer
from src.context.layers.instruction import InstructionLayer
from src.context.layers.conversation import ConversationLayer
from src.context.layers.workspace import WorkspaceLayer
from src.context.layers.file_cache import FileCacheLayer
from src.context.layers.summary import SummaryLayer, SummaryEntry

__all__ = [
    "BaseLayer",
    "InstructionLayer",
    "ConversationLayer",
    "WorkspaceLayer",
    "FileCacheLayer",
    "SummaryLayer",
    "SummaryEntry",
]
