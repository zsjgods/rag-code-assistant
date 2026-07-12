#!/usr/bin/env python3
"""Run BFCL (Berkeley Function Calling Leaderboard) v3 evaluation.

Evaluates an LLM's function calling ability against the official BFCL v3
dataset using AST (Abstract Syntax Tree) matching — the same methodology
used by the BFCL leaderboard.

Usage:
    # Quick smoke test (10 cases per category):
    python run_bfcl.py --smoke

    # Run specific categories:
    python run_bfcl.py --categories simple,multiple

    # Run all Python AST categories (simple, multiple, parallel,
    #   parallel_multiple, irrelevance) — ~1240 cases:
    python run_bfcl.py

    # Run full set with a limit per category:
    python run_bfcl.py --max 100

    # List available categories:
    python run_bfcl.py --list

BFCL v3 Python AST categories (on leaderboard):
    simple (400):             single function — pick the right one
    multiple (200):           multiple function docs — pick correct
    parallel (200):           same function, 2+ invocations
    parallel_multiple (200):  different functions, 0+ calls each
    irrelevance (240):        no function relevant — should NOT call

These categories contribute to the BFCL "Overall Accuracy (AST)" score
on the official leaderboard at gorilla.cs.berkeley.edu.
"""

import os
import sys
import time
from pathlib import Path

# Fix Windows GBK encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-6-20250514")

sys.path.insert(0, os.path.dirname(__file__))
from src.eval.bfcl_loader import (
    load_bfcl_all,
    load_bfcl_category,
    print_bfcl_info,
    CATEGORIES,
)
from src.eval.runner import run_bfcl_benchmark


def main():
    args = sys.argv[1:]

    if "--list" in args:
        print_bfcl_info()
        return

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    # Parse --smoke
    smoke = "--smoke" in args

    # Parse --categories
    categories = None
    for i, a in enumerate(args):
        if a == "--categories" and i + 1 < len(args):
            categories = [c.strip() for c in args[i + 1].split(",")]
            # Validate
            invalid = [c for c in categories if c not in CATEGORIES]
            if invalid:
                print(f"Unknown categories: {invalid}")
                print(f"Available: {list(CATEGORIES.keys())}")
                return 1

    # Parse --max
    max_cases = None
    for i, a in enumerate(args):
        if a == "--max" and i + 1 < len(args):
            max_cases = int(args[i + 1])

    # ── Load dataset ─────────────────────────────────────
    print(f"BFCL v3 Evaluation — Model: {MODEL}")
    print()

    if smoke:
        categories = list(CATEGORIES.keys())
        max_cases = 10
        print(f"Smoke test: {max_cases} cases × {len(categories)} categories")
    elif categories:
        print(f"Categories: {categories}")
    else:
        categories = list(CATEGORIES.keys())
        print(f"Running all Python AST categories: {categories}")

    if max_cases:
        print(f"Max per category: {max_cases}")
    print()

    # Download and load
    save_dir = Path(".bfcl_data")
    all_cases = load_bfcl_all(categories, save_dir=save_dir)

    total_cases = sum(len(cases) for cases in all_cases.values())
    if max_cases:
        total_cases = min(max_cases, len(all_cases.get(categories[0], []))) * len(categories)
    print(f"\nTotal test cases: {total_cases}\n")

    # ── Run evaluation ───────────────────────────────────
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
    start = time.time()

    results = run_bfcl_benchmark(
        client,
        MODEL,
        all_cases,
        categories=categories,
        max_cases_per_category=max_cases,
    )

    elapsed = time.time() - start
    print(f"\nTime: {elapsed:.1f}s  ({elapsed/60:.1f} min)")

    # ── Save detailed results ────────────────────────────
    import json
    from datetime import datetime

    out_dir = Path(".bfcl_results")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"bfcl_{MODEL.replace('/', '_')}_{ts}.json"

    # Build serializable summary
    serializable = {}
    for cat, s in results.items():
        if cat == "_overall":
            serializable[cat] = {
                "passed": s["passed"],
                "total": s["total"],
                "rate": s["rate"],
            }
        else:
            serializable[cat] = {
                "passed": s["passed"],
                "total": s["total"],
                "rate": s["rate"],
                "failures": [
                    {
                        "id": r["id"],
                        "prompt": r["prompt"][:120],
                        "reason": r["reason"],
                        "tool_calls": [
                            {"name": tc["name"], "input": dict(tc.get("input", {}))}
                            for tc in r.get("tool_calls", [])
                        ],
                        "expected": [
                            {"name": e["name"], "args": {k: v for k, v in e.get("args", {}).items()}}
                            for e in r.get("expected", [])
                        ],
                    }
                    for r in s["results"]
                    if not r["passed"]
                ],
            }

    out_path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    main()
