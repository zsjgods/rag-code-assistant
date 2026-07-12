"""30 test cases for agent-core function calling evaluation.

Design principles (matching BFCL methodology):
  - Every case has 4-6 available tools to create real selection pressure
  - Prompts are natural/conversational — no hints about which tool to use
  - No explicit "do this at the same time" or "use tool X" directives
  - Irrelevant cases include borderline questions where tools COULD be helpful

Categories:
  simple (12):     single tool, single call — must select the RIGHT one from distractors
  irrelevant (10): may or may not need tools — tests restraint vs over-eagerness
  multiple (4):    must call 2+ DIFFERENT tools sequentially in a single response
  parallel (4):    must call the SAME tool multiple times with different args
"""

# ── Simple: one correct tool, multiple distractors ──────────

SIMPLE = [
    {
        "category": "simple",
        "prompt": "I need to see what Python files exist in this project — "
                  "don't open them, just tell me what's there",
        "available_tools": ["glob", "grep", "read_file", "bash", "memory_search"],
        "expected": {"name": "glob", "required_args": ["pattern"]},
    },
    {
        "category": "simple",
        "prompt": "I think there's a bug in the login flow. Can you find all places "
                  "in the code where 'authenticate' is referenced?",
        "available_tools": ["grep", "read_file", "glob", "memory_search", "bash", "task_create"],
        "expected": {"name": "grep", "required_args": ["pattern"]},
    },
    {
        "category": "simple",
        "prompt": "The tests are failing and I need to see the output. Run pytest and show me what happens.",
        "available_tools": ["bash", "read_file", "grep", "glob", "TodoWrite", "task_create"],
        "expected": {"name": "bash", "required_args": ["command"]},
    },
    {
        "category": "simple",
        "prompt": "Show me what's written in the CLAUDE.md file at the root of this project",
        "available_tools": ["read_file", "grep", "glob", "memory_search", "scratchpad_read", "bash"],
        "expected": {"name": "read_file", "required_args": ["path"]},
    },
    {
        "category": "simple",
        "prompt": "I need to save the deployment instructions: 'step 1: build docker image, "
                  "step 2: push to registry, step 3: kubectl apply'. "
                  "Save this to a file called DEPLOY.md",
        "available_tools": ["write_file", "scratchpad_write", "edit_file", "bash", "TodoWrite", "task_create"],
        "expected": {"name": "write_file", "required_args": ["path", "content"]},
    },
    {
        "category": "simple",
        "prompt": "In the file src/config.py, the database URL is 'localhost:5432' but "
                  "it should be 'db.internal:5432'. Please make this change directly.",
        "available_tools": ["edit_file", "write_file", "bash", "read_file", "grep", "scratchpad_write"],
        "expected": {"name": "edit_file", "required_args": ["path", "old_text", "new_text"]},
    },
    {
        "category": "simple",
        "prompt": "I need to understand this codebase. Search for anything you know about "
                  "authentication patterns used in this project — check your memory first.",
        "available_tools": ["memory_search", "grep", "read_file", "glob", "bash", "scratchpad_read"],
        "expected": {"name": "memory_search", "required_args": ["query"]},
    },
    {
        "category": "simple",
        "prompt": "What does the codebase use for authentication? Search for references "
                  "to auth in the source code.",
        "available_tools": ["grep", "memory_search", "read_file", "glob", "bash", "scratchpad_read"],
        "expected": {"name": "grep", "required_args": ["pattern"]},
    },
    {
        "category": "simple",
        "prompt": "Let me track what needs to be done. Add these to my checklist: "
                  "'add unit tests' as pending, 'refactor database layer' as pending, "
                  "and mark 'fix login bug' as done.",
        "available_tools": ["TodoWrite", "task_create", "task_update", "scratchpad_write", "write_file", "bash"],
        "expected": {"name": "TodoWrite", "required_args": ["items"]},
    },
    {
        "category": "simple",
        "prompt": "I need to work with another agent on this. Save these findings to a shared "
                  "location: key=API_TIMEOUT, value=30s, key=MAX_RETRIES, value=3. "
                  "Put it in a file called shared_config.txt",
        "available_tools": ["scratchpad_write", "write_file", "scratchpad_read", "edit_file", "TodoWrite", "set_objective"],
        "expected": {"name": "scratchpad_write", "required_args": ["filename", "content"]},
    },
    {
        "category": "simple",
        "prompt": "There's a new feature request: 'users should be able to reset their password "
                  "via email'. Create a task for this so I don't forget.",
        "available_tools": ["task_create", "TodoWrite", "scratchpad_write", "write_file", "set_objective", "bash"],
        "expected": {"name": "task_create", "required_args": ["subject"]},
    },
    {
        "category": "simple",
        "prompt": "Show me all the tasks I currently have — I want to see what's pending "
                  "and what's in progress.",
        "available_tools": ["task_list", "task_get", "TodoWrite", "grep", "read_file", "scratchpad_read"],
        "expected": {"name": "task_list", "required_args": []},
    },
]

# ── Irrelevant: borderline cases, no system prompt hint ────

IRRELEVANT = [
    {
        "category": "irrelevant",
        "prompt": "What's the time complexity of quicksort in the worst case?",
        "available_tools": ["bash", "read_file", "grep", "glob", "memory_search"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "If I have a Python list of 1000 integers and I want to find the median, "
                  "which built-in function should I use — median() or statistics.median()?",
        "available_tools": ["bash", "grep", "read_file", "memory_search", "glob"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "When should I use a mutex vs a semaphore in concurrent programming?",
        "available_tools": ["bash", "read_file", "grep", "memory_search", "write_file"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "I'm thinking about using Redis for caching. What are the pros and cons "
                  "compared to in-memory caching?",
        "available_tools": ["bash", "read_file", "grep", "memory_search", "glob", "scratchpad_write"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "Can you explain how Python's GIL affects multi-threading performance?",
        "available_tools": ["bash", "read_file", "grep", "glob", "memory_search"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "Between Docker and Podman, which one should a small startup use and why?",
        "available_tools": ["bash", "grep", "read_file", "memory_search", "scratchpad_write"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "I wrote a recursive function that's hitting maximum recursion depth. "
                  "How do I fix this in Python?",
        "available_tools": ["bash", "grep", "read_file", "edit_file", "memory_search"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "What's the difference between 'git merge' and 'git rebase' and when "
                  "should I use each?",
        "available_tools": ["bash", "read_file", "grep", "glob", "memory_search"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "How does HTTPS certificate pinning work and is it still recommended in 2026?",
        "available_tools": ["bash", "grep", "read_file", "memory_search", "scratchpad_write"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "I'm designing a REST API. Should I use PUT or PATCH for partial updates?",
        "available_tools": ["bash", "read_file", "grep", "memory_search", "write_file", "glob"],
        "expected": None,
    },
    # ── Borderline cases: tools could help, but aren't strictly necessary ──
    {
        "category": "irrelevant",
        "prompt": "Does this project use pytest or unittest for testing? Take a guess based "
                  "on common Python project patterns.",
        "available_tools": ["glob", "read_file", "grep", "bash"],
        "expected": None,
    },
    {
        "category": "irrelevant",
        "prompt": "I want to understand the architecture of this project. Based on what "
                  "you know, what would you say are the main modules?",
        "available_tools": ["glob", "read_file", "grep", "memory_search", "bash"],
        "expected": None,  # It's asking for an opinion/knowledge, not a file search
    },
]

# ── Multiple: two DIFFERENT tools in sequence ────────────────
# NOTE: DeepSeek V4 only emits 1 tool_use per turn. These test
# "multi-tool single-response" capability. Models that don't support
# this will naturally fail — which is itself a useful finding.

MULTIPLE = [
    {
        "category": "multiple",
        "prompt": "I want to find all Python files that import 'asyncio', then take the "
                  "first one from the results and show me its full contents.",
        "available_tools": ["grep", "read_file", "glob", "bash", "memory_search"],
        "expected": [
            {"name": "grep", "required_args": ["pattern"]},
            {"name": "read_file", "required_args": ["path"]},
        ],
    },
    {
        "category": "multiple",
        "prompt": "There's a new requirement: 'add two-factor authentication to the login flow'. "
                  "Create a task for it, then show me all existing tasks so I can see "
                  "where it fits in priority.",
        "available_tools": ["task_create", "task_list", "TodoWrite", "scratchpad_write", "set_objective", "bash"],
        "expected": [
            {"name": "task_create", "required_args": ["subject"]},
            {"name": "task_list", "required_args": []},
        ],
    },
    {
        "category": "multiple",
        "prompt": "Search the indexed code for 'error handling middleware', then save whatever "
                  "you find to scratchpad/error_audit.txt for another agent to review.",
        "available_tools": ["memory_search", "scratchpad_write", "grep", "write_file", "read_file", "bash"],
        "expected": [
            {"name": "memory_search", "required_args": ["query"]},
            {"name": "scratchpad_write", "required_args": ["filename", "content"]},
        ],
    },
    {
        "category": "multiple",
        "prompt": "Set the current goal to 'migrate auth from JWT to OAuth2', then list "
                  "all skills to see if any are relevant to this migration.",
        "available_tools": ["set_objective", "list_skills", "task_create", "TodoWrite", "scratchpad_write", "bash"],
        "expected": [
            {"name": "set_objective", "required_args": ["objective"]},
            {"name": "list_skills", "required_args": []},
        ],
    },
]

# ── Parallel: SAME tool called 2+ times with different args ──

PARALLEL = [
    {
        "category": "parallel",
        "prompt": "I need to review the project configuration. Show me what's in settings.json, "
                  "CLAUDE.md, and pyproject.toml — I want to compare them side by side.",
        "available_tools": ["read_file", "grep", "glob", "bash", "memory_search"],
        "expected_multi": [
            {"name": "read_file", "required_args": ["path"]},
        ],
        "min_calls": 3,
    },
    {
        "category": "parallel",
        "prompt": "I need to check all Python files for both 'TODO' comments and 'FIXME' comments. "
                  "These are different searches so do both.",
        "available_tools": ["grep", "read_file", "glob", "bash"],
        "expected_multi": [
            {"name": "grep", "required_args": ["pattern"]},
        ],
        "min_calls": 2,
    },
    {
        "category": "parallel",
        "prompt": "There should be unit tests and integration tests in this project. "
                  "Can you find all test files with .py extension, and also find all "
                  "markdown documentation files?",
        "available_tools": ["glob", "grep", "read_file", "bash", "memory_search"],
        "expected_multi": [
            {"name": "glob", "required_args": ["pattern"]},
        ],
        "min_calls": 2,
    },
    {
        "category": "parallel",
        "prompt": "I need to check the status of task #1, task #5, and task #7 — "
                  "just get all three at once.",
        "available_tools": ["task_get", "task_list", "read_file", "grep", "bash"],
        "expected_multi": [
            {"name": "task_get", "required_args": ["task_id"]},
        ],
        "min_calls": 3,
    },
]

# ── Combine ─────────────────────────────────────────────────


def get_all_cases():
    """Return all test cases as a single list."""
    return SIMPLE + IRRELEVANT + MULTIPLE + PARALLEL
