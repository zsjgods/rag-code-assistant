# s_full.py v2.0

**A pedagogical Agent framework implementing Claude Code's core architecture.**

Not a LangChain alternative. A reference implementation you can read file-by-file
to understand how production agent systems work under the hood.

## What's inside

```
s_full/
├── s_full.py                    # Main entry + REPL
├── settings.json                # Default configuration
│
├── src/
│   ├── agent/
│   │   ├── loop.py              # Agent loop with hook insertion points
│   │   ├── hooks.py             # Hook system (5 lifecycle events)
│   │   └── filter_tools.py      # 3-level tool isolation for sub-agents
│   │
│   ├── compression/
│   │   ├── micro.py             # Micro-compact: clear old tool results
│   │   ├── collapse.py          # Context collapse: per-roundtrip summarization
│   │   └── auto.py              # Auto-compact: full conversation summarization
│   │
│   ├── tools/
│   │   ├── base.py              # Tool interface with safety flags
│   │   ├── registry.py          # Central tool registry
│   │   └── builtin/             # bash, read, write, edit, grep, glob
│   │
│   ├── skills/
│   │   └── loader.py            # SKILL.md parser + parameter resolver
│   │
│   ├── state/
│   │   └── store.py             # Observable Store + ToolUseContext isolation
│   │
│   ├── bus/
│   │   ├── message_bus.py       # JSONL-based inter-agent messaging
│   │   └── scratchpad.py        # Permission-free shared file space
│   │
│   ├── tasks/
│   │   ├── todo.py              # In-memory todo tracker
│   │   └── task_manager.py      # File-persisted task board
│   │
│   ├── config/
│   │   └── loader.py            # Layered config loading
│   │
│   └── recovery/
│       ├── error_handler.py     # Graded retry + exponential backoff
│       └── session.py           # Crash recovery via bridgePointer
│
├── examples/
│   └── hooks-demo/              # Hook configuration examples
│
└── tests/
    └── test_hooks.py
```

## Key features

### Hook System (Chapter 8)
5 lifecycle events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop.
Command hooks (shell scripts) and Prompt hooks (LLM evaluation).
JSON response protocol with `decision`, `updatedInput`, `additionalContext`.

### Three-Tier Compression (Chapters 5 + 7)
1. **Micro-compact**: Clear old tool results — zero cost
2. **Context collapse**: Per-roundtrip group summarization — cheap
3. **Auto-compact**: Full conversation summary — last resort

Circuit breaker: 3 consecutive failures → stop trying.

### Tool Isolation (Chapter 9)
Three-layer filtering for sub-agents:
1. Global deny list (prevent recursion and authority confusion)
2. Type-based whitelist (Explore/background/general-purpose)
3. Agent-defined allow/deny overrides

### Skills (Chapter 11)
Markdown frontmatter + parameter substitution. Conditional activation
via `paths` patterns. Placeholder support: `$ARGUMENTS`, `$1`, `${CLAUDE_SKILL_DIR}`.

### Scratchpad (Chapter 10)
Permission-free shared file space at `/tmp/s_full_<id>/scratchpad/`.
Agent A writes analysis → Agent B reads → Coordinator synthesizes.

## Quick start

```bash
# Clone
git clone https://github.com/YOUR_USER/s_full.git
cd s_full

# Install
pip install -e .

# Set API key
export ANTHROPIC_API_KEY=your-key
export MODEL_ID=claude-sonnet-4-6-20250514

# Run
python s_full.py
```

## REPL commands

| Command | Action |
|---------|--------|
| `/compact` | Manually compress conversation |
| `/tasks` | List task board |
| `/hooks` | Show hook statistics |
| `/skills` | List loaded skills |

## Hook configuration

Edit `settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo $INPUT_JSON | python3 scripts/check_bash.py",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions and comparisons.

## License

MIT
