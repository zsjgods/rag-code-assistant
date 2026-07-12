"""Summarizer — pluggable abstraction for LLM-based summarization.

CompressionPipeline depends on this interface, NOT on any specific LLM.
This decouples compression from the model provider and enables testing
without API calls.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Callable


# ── Summarizer (ABC) ────────────────────────────────────────────────────


class Summarizer(ABC):
    """Abstract summarizer — wraps any LLM or fallback strategy.

    CompressionPipeline calls summarize() during AutoCompactStage.
    The implementation is responsible for:
      1. Combining existing_summary + new messages into a coherent summary
      2. Respecting target_tokens for output length
      3. Handling errors gracefully (never raise)
    """

    @abstractmethod
    def summarize(
        self,
        *,
        messages: list[dict],
        existing_summary: str | None = None,
        target_tokens: int = 2000,
    ) -> str:
        """Summarize conversation messages into a compact representation.

        Args:
            messages: Conversation messages to summarize (list of {"role": ..., "content": ...})
            existing_summary: Previous rolling summary, or None if first compression.
            target_tokens: Target output length in tokens (approximate).

        Returns:
            Summary string. Never raises — returns fallback text on error.
        """
        ...


# ── LLMSummarizer ──────────────────────────────────────────────────────


_SUMMARIZE_SYSTEM = """You are a conversation summarizer for a coding agent.

Your task: produce a concise, structured summary that preserves continuity.

Required sections:
  - Task: current high-level goal
  - Status: what's done, what's in progress
  - Completed: specific files modified, tests written, commands run
  - Pending: what remains to be done
  - Decisions: architectural choices, design patterns agreed upon
  - Files: key files touched and why
  - Bugs Found: errors discovered and their fixes

Write in bullet points. Be specific (include file paths).
Keep under {target_tokens} tokens."""

_SUMMARIZE_WITH_EXISTING = """Here is the existing summary of work so far:

<existing-summary>
{existing}
</existing-summary>

Here are the new conversation turns to incorporate:

<new-conversation>
{conversation}
</new-conversation>

Produce a SINGLE updated summary that merges both. Use the same section format.
Do NOT include the <existing-summary> tags in your output."""

_SUMMARIZE_FIRST = """Here is the conversation to summarize:

<conversation>
{conversation}
</conversation>

Produce a structured summary covering: Task, Status, Completed, Pending, Decisions, Files, Bugs Found."""


class LLMSummarizer(Summarizer):
    """LLM-backed summarizer. Wraps any callable for LLM inference.

    Usage:
        summarizer = LLMSummarizer(llm_call=lambda prompt: client.messages.create(...).content[0].text)
        summary = summarizer.summarize(messages=conv, existing_summary=None)
    """

    def __init__(self, llm_call: Callable[[str], str]):
        """
        Args:
            llm_call: A callable that takes a prompt string and returns LLM response text.
                      Must handle errors internally (return error message text, not raise).
        """
        self._llm = llm_call

    def summarize(
        self,
        *,
        messages: list[dict],
        existing_summary: str | None = None,
        target_tokens: int = 2000,
    ) -> str:
        try:
            conv_text = json.dumps(messages, default=str)
            # Truncate if too long (prevent prompt overflow)
            if len(conv_text) > 80000:
                conv_text = "..." + conv_text[-80000:]

            system = _SUMMARIZE_SYSTEM.format(target_tokens=target_tokens)

            if existing_summary:
                user = _SUMMARIZE_WITH_EXISTING.format(
                    existing=existing_summary[:5000],
                    conversation=conv_text,
                )
            else:
                user = _SUMMARIZE_FIRST.format(conversation=conv_text)

            prompt = f"{system}\n\n{user}"
            response = self._llm(prompt)
            return response.strip() or "(summary unavailable)"
        except Exception as e:
            return f"(summarization failed: {e})"


# ── SimpleSummarizer (fallback) ─────────────────────────────────────────


class SimpleSummarizer(Summarizer):
    """Fallback summarizer — truncates conversation to fit target_tokens.

    Used when no LLM is available (testing, degraded mode).
    """

    def summarize(
        self,
        *,
        messages: list[dict],
        existing_summary: str | None = None,
        target_tokens: int = 2000,
    ) -> str:
        parts: list[str] = []

        if existing_summary:
            parts.append(f"[Previous summary]\n{existing_summary[:target_tokens * 4]}")

        # Include last few messages
        recent = messages[-6:] if len(messages) > 6 else messages
        conv_text = json.dumps(recent, default=str)
        parts.append(f"[Recent messages]\n{conv_text[:target_tokens * 2]}")

        return "\n\n".join(parts)
