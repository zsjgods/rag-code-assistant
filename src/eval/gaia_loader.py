"""GAIA benchmark loader — downloads and loads the GAIA validation set.

GAIA (General AI Assistants) by Meta AI & Hugging Face:
  - 466 real-world questions across 3 difficulty levels
  - Tests: multi-step reasoning, tool use, web search, file handling
  - Scoring: quasi exact match (normalize → strip → compare)

Dataset: huggingface.co/datasets/gaia-benchmark/GAIA
  - 2023 validation: 165 questions (public)
  - 2023 test: 301 questions (hidden labels)
"""

import json
import sys
from pathlib import Path


def download_gaia(split: str = "validation", save_dir: Path = None) -> Path:
    """Download GAIA dataset from HuggingFace using datasets library.

    Args:
        split: "validation" (165 q) or "test" (301 q, labels hidden)
        save_dir: optional directory to save JSON file

    Returns:
        Path to the saved JSON file
    """
    save_dir = save_dir or Path(".gaia_data")
    save_dir.mkdir(exist_ok=True)

    out_path = save_dir / f"gaia_{split}.json"

    # Try loading from HuggingFace
    try:
        from datasets import load_dataset
        ds = load_dataset("gaia-benchmark/GAIA", "2023_all", split=split)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load GAIA dataset. Install huggingface datasets:\n"
            f"  pip install datasets\n"
            f"Error: {e}"
        )

    questions = []
    for item in ds:
        q = {
            "task_id": item["task_id"],
            "question": item["Question"],
            "level": item["Level"],  # 1, 2, or 3
            "final_answer": item.get("Final answer", ""),
            "file_name": item.get("file_name", ""),
            "file_path": item.get("file_path", ""),
        }
        questions.append(q)

    out_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Downloaded {len(questions)} GAIA {split} questions → {out_path}")
    return out_path


def load_gaia(data_path: str | Path, levels: list[int] = None,
              max_questions: int = None) -> list[dict]:
    """Load GAIA questions from a JSON file.

    Args:
        data_path: path to gaia_*.json file
        levels: filter by difficulty levels (e.g. [1, 2])
        max_questions: limit number of questions

    Returns:
        list of question dicts
    """
    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(
            f"GAIA data not found at {data_path}. Download it first:\n"
            f"  python -c \"from src.eval.gaia_loader import download_gaia; download_gaia()\""
        )

    questions = json.loads(data_path.read_text(encoding="utf-8"))

    if levels:
        questions = [q for q in questions if q["level"] in levels]

    if max_questions:
        questions = questions[:max_questions]

    return questions


# ── Scoring: GAIA Quasi Exact Match ──────────────────────────


def normalize_answer(text: str) -> str:
    """Normalize an answer for comparison. Based on GAIA's normalization."""
    import re

    text = str(text).strip().lower()

    # Remove common prefixes that LLMs add
    prefixes = [
        "the answer is ", "answer: ", "the final answer is ",
        "final answer: ", "the result is ", "result: ",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    # Remove trailing periods
    text = re.sub(r'\.+$', '', text)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)

    # Remove commas in numbers (GAIA scoring: "1,000" == "1000")
    text = re.sub(r'(\d),(\d)', r'\1\2', text)

    # Remove articles
    text = re.sub(r'\b(the|a|an)\b', '', text)

    text = text.strip()
    return text


def score_answer(predicted: str, ground_truth: str) -> dict:
    """Score a single answer against ground truth.

    Returns:
        {"correct": bool, "predicted_norm": str, "truth_norm": str, "score": 0|1}
    """
    pred_norm = normalize_answer(predicted)
    truth_norm = normalize_answer(ground_truth)

    # Exact match after normalization
    correct = pred_norm == truth_norm

    # Also check if truth is contained in prediction (for longer answers)
    if not correct and len(truth_norm) > 10:
        correct = truth_norm in pred_norm

    return {
        "correct": correct,
        "predicted_norm": pred_norm[:200],
        "truth_norm": truth_norm[:200],
        "score": 1 if correct else 0,
    }
