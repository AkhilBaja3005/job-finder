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


SUGGESTIONS = [
    "Why do you want to work here?", "What are your salary expectations?", "What is your notice period or earliest start date?",
    "Where did you hear about this role?", "Tell us about a project you are proud of.", "Anything else you would like us to know?",
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


def save_saved_answers(root: str, items) -> Dict[str, int]:
    """Writes the list from the app's form. Blank rows are dropped, long text is cut to the limits, the file is replaced in one step."""
    clean: List[Dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        question, answer = str(item.get("question", "")).strip()[:200], str(item.get("answer", "")).strip()[:MAX_CHARS]
        if question and answer:
            clean.append({"question": question, "answer": answer})
    clean = clean[:MAX_ENTRIES]
    os.makedirs(root, exist_ok=True)
    tmp = path_for(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path_for(root))
    return {"saved": len(clean)}
