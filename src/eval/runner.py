"""Benchmark runner for agent function calling evaluation.

Runs test cases against an LLM and scores tool_use output against expected calls.
Does NOT actually execute tools — only checks whether the model's tool selection
and argument filling match expectations.

Scoring method: AST-style matching
  - Tool name must match exactly
  - All required_args must be present in the input
  - Argument values are NOT checked (equivalent expressions like "*.py" vs "**/*.py"
    are both valid for "find Python files")
"""

import json
import re
from typing import Optional
from src.tools.registry import ToolRegistry
from src.eval.test_cases import get_all_cases


def _extract_tool_calls(response):
    """Extract tool_use blocks from an Anthropic API response.

    Returns list of {"name": str, "input": dict}.
    """
    calls = []
    content = response.content if hasattr(response, "content") else []
    for block in content:
        if hasattr(block, "type") and block.type == "tool_use":
            calls.append({
                "name": block.name,
                "input": dict(block.input) if hasattr(block, "input") else {},
            })
    return calls


def _match_single(call, expected):
    """Check if a single tool call matches expected.

    Returns (passed: bool, reason: str).
    """
    # Name match
    if call["name"] != expected["name"]:
        return False, f"expected {expected['name']}, got {call['name']}"

    # Required args present
    for arg in expected.get("required_args", []):
        if arg not in call["input"]:
            return False, f"{call['name']}: missing required arg '{arg}', got {list(call['input'].keys())}"

    return True, "match"


def evaluate_case(client, model: str, registry: ToolRegistry, case: dict) -> dict:
    """Evaluate a single test case.

    Returns {"passed": bool, "category": str, "prompt": str, "reason": str,
             "tool_calls": list, "expected": ...}
    """
    # 1. Build filtered registry with only available tools for this case
    filtered = ToolRegistry()
    for name in case["available_tools"]:
        tool = registry.get(name)
        if tool:
            filtered.register(tool)
        else:
            return {
                "passed": False,
                "category": case["category"],
                "prompt": case["prompt"],
                "reason": f"Unknown tool: {name}",
                "tool_calls": [],
                "expected": case.get("expected", case.get("expected_multi", [])),
            }

    tools = filtered.to_api_format()

    # 2. Single-turn LLM call
    try:
        response = client.messages.create(
            model=model,
            system="You are an AI assistant. Use tools only when they are necessary to "
                   "answer the user's request. Choose the most appropriate tool for each task.",
            messages=[{"role": "user", "content": case["prompt"]}],
            tools=tools,
            max_tokens=1000,
        )
    except Exception as e:
        return {
            "passed": False,
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": f"API error: {e}",
            "tool_calls": [],
            "expected": case.get("expected", case.get("expected_multi", [])),
        }

    # 3. Extract tool calls
    tool_calls = _extract_tool_calls(response)

    # 4. Score
    expected = case.get("expected")

    # Parallel: special handling (uses expected_multi + min_calls)
    if "parallel" in case["category"] and "min_calls" in case:
        if len(tool_calls) < case["min_calls"]:
            return {
                "passed": False,
                "category": "parallel",
                "prompt": case["prompt"],
                "reason": f"only {len(tool_calls)} tool calls, expected at least {case['min_calls']}",
                "tool_calls": tool_calls,
                "expected": case.get("expected_multi", []),
            }
        # Check that at least min_calls match the expected_multi pattern
        matched = 0
        for tc in tool_calls:
            for em in case.get("expected_multi", []):
                ok, _ = _match_single(tc, em)
                if ok:
                    matched += 1
                    break
        if matched >= case["min_calls"]:
            return {
                "passed": True,
                "category": "parallel",
                "prompt": case["prompt"],
                "reason": f"{len(tool_calls)} calls, {matched} matched",
                "tool_calls": tool_calls,
                "expected": case.get("expected_multi", []),
            }
        return {
            "passed": False,
            "category": "parallel",
            "prompt": case["prompt"],
            "reason": f"only {matched}/{len(tool_calls)} calls matched expected pattern",
            "tool_calls": tool_calls,
            "expected": case.get("expected_multi", []),
        }

    # Irrelevant: must NOT call any tool
    if expected is None:
        if len(tool_calls) == 0:
            return {
                "passed": True,
                "category": "irrelevant",
                "prompt": case["prompt"],
                "reason": "correctly called no tools",
                "tool_calls": [],
                "expected": None,
            }
        else:
            names = [c["name"] for c in tool_calls]
            return {
                "passed": False,
                "category": "irrelevant",
                "prompt": case["prompt"],
                "reason": f"should NOT call any tool, but called: {names}",
                "tool_calls": tool_calls,
                "expected": None,
            }

    # Must have at least one tool call
    expected_list = expected if isinstance(expected, list) else [expected]

    if len(tool_calls) == 0:
        return {
            "passed": False,
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": f"no tool called, expected {[e['name'] for e in expected_list] if isinstance(expected, list) else expected['name']}",
            "tool_calls": [],
            "expected": expected,
        }

    # Simple / Multiple: sequential match
    for i, exp in enumerate(expected_list):
        if i >= len(tool_calls):
            return {
                "passed": False,
                "category": case["category"],
                "prompt": case["prompt"],
                "reason": f"step {i+1}: expected {exp['name']}, but no more tool calls",
                "tool_calls": tool_calls,
                "expected": expected,
            }
        ok, reason = _match_single(tool_calls[i], exp)
        if not ok:
            return {
                "passed": False,
                "category": case["category"],
                "prompt": case["prompt"],
                "reason": f"step {i+1}: {reason}",
                "tool_calls": tool_calls,
                "expected": expected,
            }

    return {
        "passed": True,
        "category": case["category"],
        "prompt": case["prompt"],
        "reason": f"all {len(expected_list)} steps matched",
        "tool_calls": tool_calls,
        "expected": expected,
    }


def run_benchmark(client, registry: ToolRegistry, model: str, cases=None):
    """Run all test cases and print a summary report.

    Args:
        client: Anthropic client instance
        registry: ToolRegistry with all tools registered
        model: model ID string
        cases: optional list of cases (defaults to get_all_cases())

    Returns:
        dict: {category: {"passed": int, "total": int, "failures": [...]}}
    """
    if cases is None:
        cases = get_all_cases()

    results = {"simple": [], "irrelevant": [], "multiple": [], "parallel": []}

    total = len(cases)
    for i, case in enumerate(cases):
        cat = case["category"]
        result = evaluate_case(client, model, registry, case)
        results[cat].append(result)

        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{i+1:2d}/{total}] {status} [{cat}] {case['prompt'][:60]}...")
        if not result["passed"]:
            print(f"       → {result['reason']}")

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)

    overall_passed = 0
    overall_total = 0

    for cat in ["simple", "irrelevant", "multiple", "parallel"]:
        items = results[cat]
        if not items:
            continue
        passed = sum(1 for r in items if r["passed"])
        total_cat = len(items)
        rate = passed / total_cat * 100
        bar = "#" * int(rate / 10) + "-" * (10 - int(rate / 10))
        print(f"  {cat:<15} {bar}  {passed}/{total_cat}  ({rate:.0f}%)")

        overall_passed += passed
        overall_total += total_cat

        # Print failures
        failures = [r for r in items if not r["passed"]]
        if failures:
            for f in failures:
                print(f"    FAIL {f['prompt'][:60]}")
                print(f"      {f['reason']}")

    overall_rate = overall_passed / overall_total * 100 if overall_total > 0 else 0
    overall_bar = "#" * int(overall_rate / 10) + "-" * (10 - int(overall_rate / 10))
    print(f"  {'OVERALL':<15} {overall_bar}  {overall_passed}/{overall_total}  ({overall_rate:.0f}%)")
    print("=" * 60)

    return results


# ═══════════════════════════════════════════════════════════════
#  BFCL AST Evaluation (official methodology)
# ═══════════════════════════════════════════════════════════════

def _normalize_bfcl_value(value) -> str:
    """BFCL-style value normalization: strip whitespace, standardize.

    Ported from BFCL's eval_checker logic:
      - Strings: strip whitespace, remove certain punctuation
      - Numbers: normalize int/float differences
    """
    import re
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        # BFCL allows int→float coercion
        return str(value)
    if isinstance(value, str):
        # Strip whitespace
        v = value.strip()
        # BFCL strips these punctuation chars for robustness
        v = re.sub(r'[,.\-/_*^]', '', v)
        # Collapse whitespace
        v = re.sub(r'\s+', ' ', v)
        return v.lower()
    return str(value)


def _bfcl_value_matches(predicted_value, acceptable_values: list) -> bool:
    """Check if a predicted value matches any of the acceptable values.

    BFCL ground truth stores each param as a LIST of acceptable values.
    Uses BFCL's normalization rules:
      - int → float: 10 matches 10.0
      - string: case-insensitive, whitespace-normalized
      - string→dict: models sometimes serialize nested objects as JSON strings
    """
    for acc in acceptable_values:
        # Exact match
        if predicted_value == acc:
            return True
        # int → float coercion (BFCL allows this)
        if isinstance(predicted_value, (int, float)) and isinstance(acc, (int, float)):
            if float(predicted_value) == float(acc):
                return True
        # String normalization
        if isinstance(predicted_value, str) and isinstance(acc, str):
            if _normalize_bfcl_value(predicted_value) == _normalize_bfcl_value(acc):
                return True
            # Try parsing both as JSON (models sometimes serialize nested objects)
            try:
                pv_json = json.loads(predicted_value)
                acc_json = json.loads(acc) if isinstance(acc, str) else acc
                if pv_json == acc_json:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
        # String→dict/list: predicted is a JSON string (possibly single-quoted)
        if isinstance(predicted_value, str) and isinstance(acc, (dict, list)):
            try:
                pv_parsed = json.loads(predicted_value)
                if pv_parsed == acc:
                    return True
            except (json.JSONDecodeError, TypeError):
                # Try with single quotes → double quotes
                try:
                    pv_parsed = json.loads(predicted_value.replace("'", '"'))
                    if pv_parsed == acc:
                        return True
                except (json.JSONDecodeError, TypeError):
                    pass
        # Boolean comparison
        if isinstance(predicted_value, bool) and isinstance(acc, bool):
            if predicted_value == acc:
                return True
    return False


def _bfcl_match_call(call: dict, expected: dict) -> tuple[bool, str]:
    """BFCL AST match: check if a tool call matches expected.

    Rules (ported from BFCL eval_checker):
      1. Function name must match exactly
      2. All required params must be present and match
      3. Optional params are checked if present, but not required
      4. Each param value must match one of the acceptable values
      5. int→float coercion is allowed
      6. No extra params beyond expected (BFCL is strict)

    Returns (passed: bool, reason: str).
    """
    # 1. Name match
    if call["name"] != expected["name"]:
        return False, f"name mismatch: expected '{expected['name']}', got '{call['name']}'"

    expected_args = expected.get("args", {})
    optional_params = set(expected.get("optional", []))
    call_input = call.get("input", {})

    # 2. Check all required expected params are present and match
    for param, acceptable_values in expected_args.items():
        if param not in call_input:
            if param in optional_params:
                continue  # param is optional, ok to skip
            return False, (
                f"{call['name']}: missing param '{param}', "
                f"expected one of {acceptable_values}"
            )
        if not _bfcl_value_matches(call_input[param], acceptable_values):
            return False, (
                f"{call['name']}.{param}: value '{call_input[param]}' "
                f"not in acceptable {acceptable_values}"
            )

    # 3. Check no extra (hallucinated) params — include optional in allowed
    allowed_params = set(expected_args.keys()) | optional_params
    extra = set(call_input.keys()) - allowed_params
    if extra:
        return False, (
            f"{call['name']}: unexpected params: {extra}"
        )

    return True, "AST match"


def evaluate_bfcl_case(
    client, model: str, case: dict, max_tokens: int = 1000
) -> dict:
    """Evaluate a single BFCL test case against an LLM.

    Registers the BFCL tool definitions temporarily, sends the prompt,
    then scores the response against BFCL ground truth using AST matching.

    Args:
        client: Anthropic client
        model: model ID
        case: BFCL case dict (from bfcl_loader)
        max_tokens: max tokens for LLM response

    Returns:
        {"passed": bool, "id": str, "category": str, "prompt": str,
         "reason": str, "tool_calls": list, "expected": list}
    """
    # Build temporary tool registry with BFCL functions
    registry = ToolRegistry()
    from src.tools.base import build_tool

    for func_def in case["functions"]:
        name = func_def["name"]
        desc = func_def.get("description", "")
        schema = func_def.get("input_schema", {})
        # Register with a no-op handler (evaluation doesn't actually execute)
        registry.register(build_tool(
            name=name,
            description=desc,
            input_schema=schema,
            handler=lambda **kw: f"[{name} executed]",
            is_read_only=True,
        ))

    tools = registry.to_api_format()
    ground_truth = case["ground_truth"]

    # Build system prompt — minimal, no hints
    system = (
        "You are an AI assistant. Use tools when appropriate to answer "
        "the user's request. Only call tools that are relevant to the task."
    )

    try:
        response = client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": case["prompt"]}],
            tools=tools,
            max_tokens=max_tokens,
        )
    except Exception as e:
        return {
            "passed": False,
            "id": case["id"],
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": f"API error: {e}",
            "tool_calls": [],
            "expected": ground_truth,
        }

    tool_calls = _extract_tool_calls(response)

    # ── Score according to category ──────────────────────────

    # Irrelevance: ground_truth is empty → must NOT call any tool
    if case["category"] == "irrelevance":
        if len(tool_calls) == 0:
            return {
                "passed": True,
                "id": case["id"],
                "category": "irrelevance",
                "prompt": case["prompt"],
                "reason": "correctly called no tools",
                "tool_calls": [],
                "expected": [],
            }
        else:
            names = [c["name"] for c in tool_calls]
            return {
                "passed": False,
                "id": case["id"],
                "category": "irrelevance",
                "prompt": case["prompt"],
                "reason": f"should NOT call any tool, called: {names}",
                "tool_calls": tool_calls,
                "expected": [],
            }

    # Must have ground truth
    if len(ground_truth) == 0:
        return {
            "passed": len(tool_calls) == 0,
            "id": case["id"],
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": f"no ground truth, {'no calls' if len(tool_calls)==0 else f'called {len(tool_calls)} tools'}",
            "tool_calls": tool_calls,
            "expected": ground_truth,
        }

    # Must have at least one tool call
    if len(tool_calls) == 0:
        return {
            "passed": False,
            "id": case["id"],
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": f"no tool called, expected {[e['name'] for e in ground_truth]}",
            "tool_calls": [],
            "expected": ground_truth,
        }

    # ── Parallel / Parallel Multiple ──────────────────────────
    # BFCL: every ground_truth entry must be matched by SOME tool call
    # Order doesn't matter; extra calls are allowed
    if case["category"] in ("parallel", "parallel_multiple"):
        matched = 0
        reasons = []
        used = set()  # track which gt entries are matched

        for gi, gt_entry in enumerate(ground_truth):
            found = False
            for ti, tc in enumerate(tool_calls):
                if ti in used:
                    continue
                ok, reason = _bfcl_match_call(tc, gt_entry)
                if ok:
                    matched += 1
                    used.add(ti)
                    found = True
                    break
            if not found:
                # Give a more detailed reason for debugging
                for tc in tool_calls:
                    ok, r = _bfcl_match_call(tc, gt_entry)
                    reasons.append(f"gt[{gi}] vs call: {r}")

        passed = matched >= len(ground_truth)
        # BFCL allows extra calls (non-greedy), but flag them
        extra = len(tool_calls) - len(ground_truth)
        reason = f"{matched}/{len(ground_truth)} ground truth matched"
        if extra > 0:
            reason += f" ({extra} extra calls)"

        return {
            "passed": passed,
            "id": case["id"],
            "category": case["category"],
            "prompt": case["prompt"],
            "reason": reason,
            "tool_calls": tool_calls,
            "expected": ground_truth,
            "_detail": reasons if not passed else None,
        }

    # ── Simple / Multiple: sequential match ────────────────────
    # BFCL: expected sequence of calls, order matters
    for i, gt_entry in enumerate(ground_truth):
        if i >= len(tool_calls):
            return {
                "passed": False,
                "id": case["id"],
                "category": case["category"],
                "prompt": case["prompt"],
                "reason": f"step {i+1}: expected '{gt_entry['name']}', no more calls",
                "tool_calls": tool_calls,
                "expected": ground_truth,
            }
        ok, reason = _bfcl_match_call(tool_calls[i], gt_entry)
        if not ok:
            return {
                "passed": False,
                "id": case["id"],
                "category": case["category"],
                "prompt": case["prompt"],
                "reason": f"step {i+1}: {reason}",
                "tool_calls": tool_calls,
                "expected": ground_truth,
            }

    return {
        "passed": True,
        "id": case["id"],
        "category": case["category"],
        "prompt": case["prompt"],
        "reason": f"all {len(ground_truth)} steps AST matched",
        "tool_calls": tool_calls,
        "expected": ground_truth,
    }


def run_bfcl_benchmark(
    client,
    model: str,
    cases: dict[str, list[dict]],
    categories: Optional[list[str]] = None,
    max_cases_per_category: Optional[int] = None,
) -> dict:
    """Run BFCL evaluation across categories.

    Args:
        client: Anthropic client
        model: model ID
        cases: {category: [case_dicts]} from load_bfcl_all()
        categories: which categories to run (default: all)
        max_cases_per_category: limit cases per category (for quick sampling)

    Returns:
        {category: {"passed": int, "total": int, "results": [...], "rate": float}}
    """
    if categories is None:
        categories = list(cases.keys())

    summary = {}
    all_results = []

    for cat in categories:
        cat_cases = cases.get(cat, [])
        if max_cases_per_category:
            cat_cases = cat_cases[:max_cases_per_category]
        if not cat_cases:
            continue

        cat_results = []
        for i, case in enumerate(cat_cases):
            result = evaluate_bfcl_case(client, model, case)
            cat_results.append(result)
            all_results.append(result)

            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"[{i+1:3d}/{len(cat_cases)}] {status} "
                f"[{cat}] {result['prompt'][:60]}..."
            )
            if not result["passed"]:
                print(f"        → {result['reason']}")
                # Show detail for failed calls
                if result.get("_detail"):
                    for d in result["_detail"][:3]:
                        print(f"          {d}")

        passed = sum(1 for r in cat_results if r["passed"])
        total = len(cat_results)
        rate = passed / total * 100 if total > 0 else 0
        summary[cat] = {
            "passed": passed,
            "total": total,
            "rate": rate,
            "results": cat_results,
        }

    # ── Print summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BFCL v3 EVALUATION SUMMARY")
    print("=" * 60)

    total_passed = 0
    total_cases = 0

    for cat in sorted(summary.keys()):
        s = summary[cat]
        bar = "#" * int(s["rate"] / 10) + "-" * (10 - int(s["rate"] / 10))
        print(f"  {cat:<22} {bar}  {s['passed']}/{s['total']}  ({s['rate']:.0f}%)")
        total_passed += s["passed"]
        total_cases += s["total"]

    overall_rate = total_passed / total_cases * 100 if total_cases > 0 else 0
    overall_bar = "#" * int(overall_rate / 10) + "-" * (10 - int(overall_rate / 10))
    print(f"  {'OVERALL':<22} {overall_bar}  {total_passed}/{total_cases}  "
          f"({overall_rate:.0f}%)")
    print("=" * 60)
    print(f"  Model: {model}")
    print(f"  Categories: {', '.join(sorted(summary.keys()))}")
    print("=" * 60)

    summary["_overall"] = {
        "passed": total_passed,
        "total": total_cases,
        "rate": overall_rate,
        "all_results": all_results,
    }
    return summary
