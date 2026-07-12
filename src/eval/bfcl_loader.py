"""BFCL (Berkeley Function Calling Leaderboard) v3 dataset loader.

Downloads and parses the official BFCL v3 dataset from HuggingFace:
  huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard

Dataset structure:
  - One JSONL file per category (simple, multiple, parallel, parallel_multiple, irrelevance, ...)
  - Ground truth in separate possible_answer/ directory
  - Each JSONL line is a full record

Evaluation categories (Python AST):
  simple (400):         single function call — pick the right one
  multiple (200):       multiple function docs — pick the correct one
  parallel (200):       same function, 2+ invocations with different args
  parallel_multiple (200): different functions, called 0+ times each
  irrelevance (240):    no function is relevant — should NOT call any
"""

import json
import os
import urllib.request
from pathlib import Path
from typing import Optional

# ── BFCL dataset URLs ─────────────────────────────────────────

HF_BASE = (
    "https://huggingface.co/datasets/gorilla-llm/"
    "Berkeley-Function-Calling-Leaderboard/resolve/main"
)

CATEGORIES = {
    "simple":             "BFCL_v3_simple.json",
    "multiple":           "BFCL_v3_multiple.json",
    "parallel":           "BFCL_v3_parallel.json",
    "parallel_multiple":  "BFCL_v3_parallel_multiple.json",
    "irrelevance":        "BFCL_v3_irrelevance.json",
}

ANSWER_FILES = {k: f"possible_answer/{v}" for k, v in CATEGORIES.items()}

# Categories available but not in default Python run:
#   java, javascript, sql, rest, chatable,
#   exec_simple/multiple/parallel/parallel_multiple,
#   live_simple/multiple/parallel/parallel_multiple/relevance/irrelevance,
#   multi_turn_base/composite/long_context/miss_func/miss_param


# ── Download helpers ──────────────────────────────────────────

def _download_jsonl(url: str) -> list[dict]:
    """Download a BFCL JSONL file and return parsed lines."""
    req = urllib.request.Request(url, headers={"User-Agent": "agent-core-bfcl-eval/1.0"})
    with urllib.request.urlopen(req) as resp:
        text = resp.read().decode("utf-8").strip()
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def _cache_path(save_dir: Path, filename: str) -> Path:
    return save_dir / filename


def _load_or_download(save_dir: Path, filename: str, url: str) -> list[dict]:
    """Load cached JSONL or download from HF."""
    path = _cache_path(save_dir, filename)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    data = _download_jsonl(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return data


# ── BFCL → Internal format conversion ──────────────────────

def _normalize_type(schema: dict) -> dict:
    """Convert BFCL schema quirks to OpenAI/Anthropic-compatible JSON Schema.

    BFCL quirks fixed:
      - {"type": "dict"} → {"type": "object"}
      - {"type": "float"} → {"type": "number"}  (float is not valid JSON Schema)
    """
    if not isinstance(schema, dict):
        return schema
    if schema.get("type") == "dict":
        schema = {**schema, "type": "object"}
    elif schema.get("type") == "float":
        schema = {**schema, "type": "number"}
    elif schema.get("type") == "tuple":
        schema = {**schema, "type": "array"}  # tuple → array (no tuple in JSON Schema)

    # Recurse into properties (each value is a sub-schema)
    if "properties" in schema and isinstance(schema["properties"], dict):
        schema["properties"] = {
            k: _normalize_type(v) if isinstance(v, dict) else v
            for k, v in schema["properties"].items()
        }

    # Recurse into items (in JSON Schema, items IS a sub-schema directly)
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = _normalize_type(schema["items"])

    # Recurse into additionalProperties
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        schema["additionalProperties"] = _normalize_type(schema["additionalProperties"])

    # Recurse into anyOf / oneOf / allOf arrays
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            schema[key] = [
                _normalize_type(s) if isinstance(s, dict) else s
                for s in schema[key]
            ]

    return schema


def _sanitize_name(name: str) -> str:
    """Sanitize BFCL function names for API compatibility.

    BFCL uses names like 'math.factorial', 'triangle_properties.get', etc.
    The API only accepts '^[a-zA-Z0-9_-]+$', so we replace '.' with '_'.
    """
    return name.replace(".", "_")


def _bfcl_to_api_tool(func_def: dict) -> dict:
    """Convert a single BFCL function definition to API tool format.

    BFCL format:
      {"name": "...", "description": "...", "parameters": {"type": "dict", ...}}

    Returns Anthropic/OpenAI tool format:
      {"name": "...", "description": "...", "input_schema": {"type": "object", ...}}
    """
    params = func_def.get("parameters", {})
    if isinstance(params, (dict,)):
        params = _normalize_type(dict(params))
    # Remove default values from schema — they confuse some models
    for prop_name, prop_val in params.get("properties", {}).items():
        if isinstance(prop_val, dict) and "default" in prop_val:
            # Keep default info in description so model can infer
            default_val = prop_val.pop("default")
            desc = prop_val.get("description", "")
            if desc:
                prop_val["description"] = f"{desc} (default: {default_val})"
            else:
                prop_val["description"] = f"Default: {default_val}"
    # Sanitize name for API compatibility (dots → underscores)
    raw_name = func_def["name"]
    safe_name = _sanitize_name(raw_name)
    return {
        "name": safe_name,
        "raw_name": raw_name,  # keep original for ground truth matching
        "description": func_def.get("description", ""),
        "input_schema": params,
    }


def _parse_ground_truth(gt_list: list, func_defs: list[dict] = None) -> list[dict]:
    """Parse BFCL ground truth into list of {name, input} dicts.

    BFCL ground truth format:
      [{"func_name": {"param1": [value1, value2], "param2": [value3]}}, ...]

    Each param value is a LIST of acceptable values (alternatives).
    Empty string "" means the parameter can be absent (optional).
    Names are sanitized to match what the model sees (dots → underscores).

    Returns list of {"name": str, "args": {param: [values]}, "optional": [params]}
    """
    result = []
    for entry in gt_list:
        if not isinstance(entry, dict):
            continue
        for func_name, params in entry.items():
            call = {"name": _sanitize_name(func_name), "args": {}, "optional": []}
            for param_name, values in params.items():
                if not isinstance(values, list):
                    values = [values]
                # Check if param is optional (has "" in acceptable values)
                has_empty = "" in values
                real_values = [v for v in values if v != ""]
                if has_empty and not real_values:
                    # Fully optional — all values are empty string
                    call["optional"].append(param_name)
                elif real_values:
                    call["args"][param_name] = real_values
                    if has_empty:
                        call["optional"].append(param_name)
            result.append(call)
    return result


def _extract_user_text(question) -> str:
    """Extract the user message text from BFCL's question field.

    question format: [[{"role": "user", "content": "..."}]]
    """
    if isinstance(question, list):
        for turn in question:
            if isinstance(turn, list):
                for msg in turn:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        return msg.get("content", "")
    return str(question)


def load_bfcl_category(
    category: str,
    save_dir: Optional[Path] = None,
) -> list[dict]:
    """Load a single BFCL category.

    Args:
        category: one of "simple", "multiple", "parallel", "parallel_multiple", "irrelevance"
        save_dir: cache directory (defaults to .bfcl_data/)

    Returns:
        List of test case dicts:
          {"id": str, "category": str, "prompt": str,
           "functions": [api_tool_format, ...],
           "ground_truth": [{"name": str, "args": {param: [values]}}, ...]}
    """
    if category not in CATEGORIES:
        raise ValueError(f"Unknown BFCL category '{category}'. Options: {list(CATEGORIES)}")

    save_dir = save_dir or Path(".bfcl_data")
    filename = CATEGORIES[category]
    answer_file = ANSWER_FILES[category]

    questions = _load_or_download(save_dir, filename, f"{HF_BASE}/{filename}")

    # Irrelevance: no separate answer file — ground truth is always empty (no calls)
    if category == "irrelevance":
        cases = []
        for q in questions:
            prompt = _extract_user_text(q.get("question", ""))
            funcs = [_bfcl_to_api_tool(f) for f in q.get("function", [])]
            cases.append({
                "id": q["id"],
                "category": category,
                "prompt": prompt,
                "functions": funcs,
                "ground_truth": [],  # must NOT call any function
                "_raw_question": q,
                "_raw_answer": [],
            })
        return cases

    # All other categories: load ground truth from possible_answer/
    answers = _load_or_download(save_dir, answer_file, f"{HF_BASE}/{answer_file}")
    answer_by_id = {a["id"]: a.get("ground_truth", []) for a in answers}

    cases = []
    for q in questions:
        qid = q["id"]
        gt_raw = answer_by_id.get(qid, [])

        # Parse ground truth
        gt = _parse_ground_truth(gt_raw)

        # Build prompt
        prompt = _extract_user_text(q.get("question", ""))

        # Convert function definitions to API format
        funcs = [_bfcl_to_api_tool(f) for f in q.get("function", [])]

        cases.append({
            "id": qid,
            "category": category,
            "prompt": prompt,
            "functions": funcs,
            "ground_truth": gt,
            # Raw fields for debugging
            "_raw_question": q,
            "_raw_answer": gt_raw,
        })

    return cases


def load_bfcl_all(
    categories: Optional[list[str]] = None,
    save_dir: Optional[Path] = None,
) -> dict[str, list[dict]]:
    """Load multiple BFCL categories.

    Returns:
        {category_name: [test_cases, ...]}
    """
    if categories is None:
        categories = list(CATEGORIES.keys())

    result = {}
    for cat in categories:
        print(f"Loading BFCL: {cat}...")
        result[cat] = load_bfcl_category(cat, save_dir)
        print(f"  → {len(result[cat])} cases")
    return result


# ── Quick info ─────────────────────────────────────────────────

def print_bfcl_info():
    """Print summary info about BFCL categories."""
    print("BFCL v3 — Berkeley Function Calling Leaderboard")
    print("=" * 50)
    total = 0
    for cat, filename in CATEGORIES.items():
        url = f"{HF_BASE}/{filename}"
        print(f"  {cat:<22}  {filename}")
        total += 1
    print(f"\n  Total categories: {total}")
    print(f"  Python AST subsets: ~1240 cases")
    print(f"  Repository: {HF_BASE}")


if __name__ == "__main__":
    print_bfcl_info()
