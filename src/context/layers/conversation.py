"""ConversationLayer — FIFO message history.

Wraps the messages list that agent_loop reads and writes. Maintains list
identity so that compression code (messages[:] = collapsed) continues to work.

Single responsibility: store and expose conversation messages.
Token budget control is a cross-cutting concern — it belongs to the
BudgetManager (M3), not to any single layer.
"""

from src.context.layers.base import BaseLayer


class ConversationLayer(BaseLayer):
    """Conversation history — FIFO message storage.

    The critical invariant: get_messages() returns the ACTUAL internal list
    reference (not a copy). This is essential for backward compatibility with
    the compression pipeline which does in-place slice assignment.

    Token counting (token_count()) is provided as passive metadata.
    Budget enforcement belongs to BudgetManager (M3).
    """

    is_immutable = False  # CAN and WILL be compressed

    def __init__(self, messages: list[dict] | None = None):
        self._messages: list[dict] = messages if messages is not None else []

    @property
    def name(self) -> str:
        return "conversation"

    # ── Render ──────────────────────────────────────────

    def render(self) -> list[dict]:
        """Return the messages list for the API call."""
        return self._messages

    # ── Mutation ────────────────────────────────────────

    def add_message(self, role: str, content) -> None:
        """Append a message to the conversation."""
        self._messages.append({"role": role, "content": content})

    def replace_messages(self, new_messages: list[dict]) -> None:
        """Replace all messages in-place, preserving list identity.

        Equivalent to messages[:] = collapsed in the current compression code.
        External references to this list remain valid.
        """
        self._messages[:] = new_messages

    def clear(self) -> None:
        """Remove all messages."""
        self._messages.clear()

    # ── Access ──────────────────────────────────────────

    def get_messages(self) -> list[dict]:
        """Return the raw messages list.

        IMPORTANT: Returns the ACTUAL internal list reference, not a copy.
        This is REQUIRED for compression compatibility.
        """
        return self._messages

    # ── Metadata (passive — no enforcement) ─────────────

    def token_count(self) -> int:
        """Estimate tokens. Passive metadata only.

        Budget enforcement is the responsibility of BudgetManager (M3),
        which calls this method as a data source.
        """
        from src.compression.micro import estimate_tokens

        return estimate_tokens(self._messages)

    # ── Sequence protocol (for backward compat iteration) ─

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)

    def __getitem__(self, idx):
        return self._messages[idx]
