"""Context collapse — mid-tier compression + importance scoring.

Groups messages by API round-trip, summarizes each middle group via LLM,
and classifies importance to prevent goal drift during compression.

Importance levels:
  goal_declaration  — user changes the main task (→ Store, compression-immune)
  error_fix         — bug found and fixed (→ Store)
  decision_made     — important architectural choice (→ Store)
  intermediate_step — normal work progress (normal summary)
  chitchat          — small talk, naming, minor edits (aggressive summary)
"""

import json
from typing import Callable


def _group_by_roundtrip(messages: list) -> list[list]:
    """Group messages by API round-trip.

    Each group starts with an assistant message and includes all
    subsequent tool_results until the next assistant message.
    """
    groups: list[list] = []
    current: list = []

    for msg in messages:
        if msg["role"] == "assistant" and current:
            groups.append(current)
            current = []
        current.append(msg)

    if current:
        groups.append(current)

    return groups


def _extract_json(text: str) -> dict | None:
    """Extract JSON object from LLM output (may have surrounding text)."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except (json.JSONDecodeError, KeyError):
        pass
    return None


SCORING_PROMPT = """Analyze this conversation round and output JSON:

{
  "summary": "one-sentence summary of what happened",
  "importance": "goal_declaration | error_fix | decision_made | intermediate_step | chitchat",
  "key_facts": ["fact 1", "fact 2"]
}

Importance definitions:
- goal_declaration:  user explicitly changes the MAIN task (not sub-steps).
   Examples: "instead of X, let's do Y", "actually, forget that, now do Z"
   NOT: "also run the tests" (still same goal), "next add error handling" (sub-step)
- error_fix:         a bug/error was discovered AND fixed. Preserve root cause + fix.
- decision_made:     a non-trivial design choice was made (file structure, algorithm, naming convention for major modules)
- intermediate_step: normal work — reading files, writing code, running commands.
   This is the DEFAULT for most rounds.
- chitchat:          small talk, naming bikeshedding, minor formatting, greetings.

=== FEW-SHOT EXAMPLES ===

Example 1 — decision_made (hardest to classify):
ROUND: User asked about auth flow. Agent read auth.py, proposed JWT + refresh token pattern split into auth/jwt.py and auth/session.py. User agreed.
OUTPUT: {"summary": "Decided on JWT+refresh token auth pattern, splitting auth.py into jwt.py and session.py", "importance": "decision_made", "key_facts": ["auth uses JWT+refresh token", "auth.py split into jwt.py and session.py"]}

Example 2 — intermediate_step (default for most rounds):
ROUND: Agent ran grep for "TODO" in src/, found 12 matches across 4 files, listed them for the user. No decisions were made, no errors occurred.
OUTPUT: {"summary": "Found 12 TODO markers across src/: loop.py(3), hooks.py(4), collapse.py(2), main.py(3)", "importance": "intermediate_step", "key_facts": ["12 TODOs found", "files: loop.py, hooks.py, collapse.py, main.py"]}

Example 3 — error_fix:
ROUND: Agent ran pytest, 3 tests failed with "KeyError: 'model'". Traced to config/loader.py line 47 using .get() without default. Changed to config.get('model', 'claude-sonnet-4-6'). All 3 tests now pass.
OUTPUT: {"summary": "Fixed KeyError in config/loader.py line 47 — .get('model') had no default, changed to .get('model', 'claude-sonnet-4-6'); all 3 tests pass", "importance": "error_fix", "key_facts": ["config/loader.py:47 .get('model') missing default caused KeyError", "fixed by adding default 'claude-sonnet-4-6'", "3 tests now pass"]}

Example 4 — chitchat:
ROUND: User asked "what's the weather like today". Agent replied that it doesn't have weather access.
OUTPUT: {"summary": "User asked about weather, agent couldn't answer", "importance": "chitchat", "key_facts": []}

=== END EXAMPLES ===

Only output the JSON object, no other text.

Conversation round:
"""


def _summarize_and_score(group: list, llm_call: Callable) -> dict:
    """Summarize a single round-trip group and return importance-scored result.

    Returns:
        {"summary": str, "importance": str, "key_facts": list}
    """
    group_text = json.dumps(group, default=str)

    # Small groups: don't bother calling LLM, classify as intermediate_step
    if len(group_text) < 2000:
        return {
            "summary": json.dumps(group, default=str),
            "importance": "intermediate_step",
            "key_facts": [],
        }

    prompt = SCORING_PROMPT + group_text

    try:
        response = llm_call(prompt)
        parsed = _extract_json(response)
        if parsed:
            return {
                "summary": parsed.get("summary", response[:500]),
                "importance": parsed.get("importance", "intermediate_step"),
                "key_facts": parsed.get("key_facts", []),
            }
        # Fallback: LLM didn't output valid JSON, treat whole response as summary
        return {
            "summary": response[:1000],
            "importance": "intermediate_step",
            "key_facts": [],
        }
    except Exception:
        # LLM call failed — return raw text as fallback
        return {
            "summary": json.dumps(group, default=str)[:2000],
            "importance": "intermediate_step",
            "key_facts": [],
        }


# Importance levels that get persisted to Store (compression-immune)
PERSIST_LEVELS = {"goal_declaration", "error_fix", "decision_made"}


def context_collapse(
    messages: list,
    llm_call: Callable,
    keep_head: int = 3,
    keep_tail: int = 3,
    on_important: Callable[[str, list[str]], None] | None = None,
) -> list | None:
    """
    Mid-tier compression: keep head/tail verbatim, summarize + score middle groups.

    High-importance events (goal_declaration, error_fix, decision_made)
    are reported via on_important(importance_level, key_facts) for persistent storage.

    Returns new messages list if compression applied, None if not needed.
    """
    groups = _group_by_roundtrip(messages)

    if len(groups) <= keep_head + keep_tail + 2:
        return None

    head = groups[:keep_head]
    middle = groups[keep_head:-keep_tail]
    tail = groups[-keep_tail:]

    summaries = []
    for group in middle:
        scored = _summarize_and_score(group, llm_call)

        # Report high-importance events to Store
        if scored["importance"] in PERSIST_LEVELS and on_important:
            on_important(scored["importance"], scored.get("key_facts", []))

        # Build compressed message
        imp = scored["importance"]
        if imp == "chitchat":
            content = f"[collapsed:chitchat] {scored['summary'][:200]}"
        elif imp == "intermediate_step":
            content = f"[collapsed]\n{scored['summary']}"
        else:
            # High-importance: mark explicitly so LLM knows it's preserved
            content = (
                f"[collapsed | IMPORTANT: {imp} — persisted to persistent store]\n"
                f"{scored['summary']}"
            )

        summaries.append({"role": "user", "content": content})

    result = []
    for g in head:
        result.extend(g)
    result.extend(summaries)
    for g in tail:
        result.extend(g)

    return result


class CollapseCircuitBreaker:
    """Prevents infinite compression loops. Fuses after N consecutive failures."""

    def __init__(self, max_failures: int = 3):
        self.max_failures = max_failures
        self._failures: int = 0
        self._open: bool = False

    def record_success(self):
        self._failures = 0
        self._open = False

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.max_failures:
            self._open = True

    @property
    def is_open(self) -> bool:
        return self._open

    def reset(self):
        self._failures = 0
        self._open = False
