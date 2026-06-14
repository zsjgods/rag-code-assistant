# Architecture

## Design principles

1. **Module-level separation**: Each module has one clear responsibility. You can read `hooks.py` without understanding `collapse.py`.

2. **Fail-closed defaults**: Safety flags default to unsafe. `isReadOnly=False` unless explicitly set. A tool is concurrency-unsafe until proven safe.

3. **Observer + Chain of Responsibility**: Hooks follow this dual pattern — multiple hooks observe the same event, executed in priority order, any hook can block the chain.

4. **Progressive compression**: Cheapest option first (micro), then mid-tier (collapse), then expensive (auto). Circuit breaker prevents infinite loops.

## Hook system design

```
Lifecycle event fires
  -> Collect matching hooks
  -> Security gate (global disable? managed-only? workspace trusted?)
  -> Sort by priority (local > project > user)
  -> Execute in order
  -> First "block" decision wins
  -> Merge additionalContext from all hooks
```

### Exit code semantics

| Exit code | JSON decision | Result |
|-----------|--------------|--------|
| 0 | approve/none | Pass silently |
| 0 | block | Block (JSON wins) |
| 2 | any | Block, stderr shown to model |
| Other non-0 | approve | Warn but continue |
| Other non-0 | block | Block |

## Three-tier compression

```
Needs compression?
  -> Tier 1: microcompact (clear old tool_results, zero cost)
     Still need more?
  -> Tier 2: context_collapse (group by roundtrip, summarize middle)
     Still need more?
  -> Tier 3: auto_compact (full LLM summary, most expensive)

Circuit breaker: 3 consecutive failures -> stop trying (day-25万-API-calls prevention)
```

### Why roundtrip grouping?

Grouping by API roundtrip (assistant -> tool_results) rather than by user turn
preserves the causal chain of tool calls within a single interaction.
Splitting a tool_call from its result loses "why the model called this tool."

## Tool isolation (three layers)

```
Layer 1: GLOBAL_DENY
  - Prevent recursion: no Agent, spawn_teammate from sub-agents
  - Prevent authority confusion: no plan_approval, shutdown_request

Layer 2: Type-based whitelist
  - Explore: readonly tools only (bash, read, grep, glob)
  - Background: limited set (Read, Write, Bash, Grep)
  - General-purpose: all tools (minus global deny)

Layer 3: Agent-defined overrides
  - allowedTools / disallowedTools from agent definition
```

## Scratchpad

Physical: `/tmp/s_full_{session_id}/scratchpad/`

Design rationale:
- No permission prompts (agents read/write freely)
- Durable (persists across agent invocations, unlike messages)
- Session-isolated (different sessions don't collide)
- Structure-free (agents organize files as needed)

## Error recovery

```
Error -> categorize
  RATE_LIMIT: retry with exponential backoff (1s -> 2s -> 4s)
  CONTEXT_TOO_LONG: trigger compression, then retry
  TRANSIENT: retry with backoff
  FATAL: don't retry, report immediately
```

## Compared to Claude Code

| Dimension | s_full.py | Claude Code |
|-----------|-----------|-------------|
| Agent loop | while True + AsyncGenerator | AsyncGenerator (query.ts 1729 lines) |
| Hooks | 5 events, 2 types | 26 events, 5 types |
| Compression | 3 tiers + circuit breaker | 6 paths + multi-system mutual exclusion |
| Tool isolation | 3-layer filter | 3-layer + hardcoded mcp__ passthrough |
| Sub-agent | run_subagent() | AgentTool with Fork/Coordinator modes |
| State management | Store (subscribe) | 4-layer (module closure + Store + ToolUseContext + bridgePointer) |
| Skills | SKILL.md parse | 5-source parallel load + dynamic discovery + conditional activation |
| MCP | Not implemented | 8 transports, 4-layer security, Bridge system |
