"""Answers the user wrote once for questions a profile cannot cover ("Why do you want to work here?", "Earliest start date").

They live in saved_answers.json next to the profile: a list of {"question": "...", "answer": "..."}. The agent is told to
use them word for word when a form question means the same thing, instead of inventing an answer."""
from __future__ import annotations

import json
import os
from typing import Dict, List

FILE_NAME = "saved_answers.json"
MAX_ENTRIES = 40
MAX_CHARS = 600
TEMPLATE = [
    {"question": "Why do you want to work here?", "answer": "Write your own answer here, or delete this example."},
    {"question": "Earliest start date", "answer": "Available to start immediately."},
]


def path_for(root: str) -> str:
    return os.path.join(root, FILE_NAME)


def ensure_template(root: str) -> str:
    """Creates the file with two examples if it does not exist yet. Returns its path."""
    path = path_for(root)
    if not os.path.exists(path):
        os.makedirs(root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(TEMPLATE, f, indent=2, ensure_ascii=False)
    return path


def load_saved_answers(root: str) -> List[Dict[str, str]]:
    try:
        with open(path_for(root), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out: List[Dict[str, str]] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and str(item.get("question", "")).strip() and str(item.get("answer", "")).strip():
            out.append({"question": str(item["question"]).strip()[:200], "answer": str(item["answer"]).strip()[:MAX_CHARS]})
    return out[:MAX_ENTRIES]


def prompt_block(root: str) -> str:
    """Text for the agent's task prompt. Empty when there are no answers."""
    answers = load_saved_answers(root)
    if not answers:
        return ""
    lines = "\n".join(f"           - Question: {a['question']}\n             Answer: {a['answer']}" for a in answers)
    return (
        "         - SAVED ANSWERS (written by the candidate). When a form question means the same as one of these, "
        "type the answer exactly as written. Do not rephrase it and do not invent a different one:\n" + lines + "\n"
    )
