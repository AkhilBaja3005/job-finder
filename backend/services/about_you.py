"""Questions a resume cannot answer, asked once in the desktop app and saved into the user's candidate_profile.json.

Forms ask about work rights, notice period, salary and (optionally) equal-opportunity details. Nothing on a resume says these, and
a wrong guess costs real applications, so the agent must use what the user chose and never an invented default."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

PREFER_NOT = "Prefer not to say"
LEVELS = ["Intern", "Junior", "Mid", "Senior", "Staff", "Lead", "Manager"]   # words services/relevance.py understands

# section, key, where it lives in the profile, label, kind, options, help
FIELDS: List[Dict[str, Any]] = [
    {"key": "work_authorization", "in": "candidate", "section": "Work rights", "label": "Where can you work?", "kind": "choice", "required": True,
     "options": ["Authorised to work in the UK without restriction", "Authorised to work in the EU / EEA without restriction",
                 "Authorised to work in the US without restriction", "Authorised to work in Canada without restriction",
                 "I need a visa to work (sponsorship)", "I have a visa that allows me to work for now"],
     "help": "Almost every form asks. Pick one, or type your own."},
    {"key": "requires_sponsorship", "in": "candidate", "section": "Work rights", "label": "Will you need visa sponsorship, now or later?", "kind": "bool", "required": True,
     "help": "Answered Yes or No on forms. If you are not sure, answer Yes: it is safer to be asked than to be turned down later."},
    {"key": "citizenship", "in": "candidate", "section": "Work rights", "label": "Citizenship", "kind": "text", "required": False, "placeholder": "e.g. United Kingdom"},
    {"key": "notice_period", "in": "candidate", "section": "Availability and pay", "label": "When can you start?", "kind": "choice", "required": True,
     "options": ["Immediately", "1 week", "2 weeks", "1 month", "2 months", "3 months"], "help": "Used for notice period and start date questions."},
    {"key": "salary_expectations", "in": "candidate", "section": "Availability and pay", "label": "Salary expectation", "kind": "text", "required": False,
     "placeholder": "e.g. 35,000 to 40,000 GBP a year", "help": "Only typed when a form asks. Leave empty and the agent answers that it is open to discussion."},
    {"key": "postal_code", "in": "candidate", "section": "Availability and pay", "label": "Postcode", "kind": "text", "required": False, "placeholder": "e.g. EC1A 1BB"},
    {"key": "seniority", "in": "search_preferences", "section": "What you are looking for", "label": "Which levels?", "kind": "multi", "required": True,
     "options": LEVELS, "help": "Jobs whose title points to a level you did not pick are skipped, for example Senior when you chose Intern."},
    {"key": "gender", "in": "candidate", "section": "Optional: equal-opportunity forms", "label": "Gender", "kind": "choice", "required": False,
     "options": [PREFER_NOT, "Female", "Male", "Non-binary"], "default": PREFER_NOT},
    {"key": "ethnicity", "in": "candidate", "section": "Optional: equal-opportunity forms", "label": "Ethnicity", "kind": "text", "required": False, "default": PREFER_NOT},
    {"key": "veteran_status", "in": "candidate", "section": "Optional: equal-opportunity forms", "label": "Veteran status", "kind": "choice", "required": False,
     "options": [PREFER_NOT, "Yes", "No"], "default": PREFER_NOT},
    {"key": "disability_status", "in": "candidate", "section": "Optional: equal-opportunity forms", "label": "Disability", "kind": "choice", "required": False,
     "options": [PREFER_NOT, "Yes", "No"], "default": PREFER_NOT},
]
SPEC = {f["key"]: f for f in FIELDS}


class AboutYouError(ValueError):
    """The answers were not valid, or there is no profile yet. The message is safe to show."""


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _filled(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (list, str, dict)):
        return bool(value) and not (isinstance(value, str) and not value.strip())
    return value is not None


def read_about_you(profile_path: str) -> Dict[str, Any]:
    """The questions with their current answers. `unanswered` lists the required ones with no answer yet."""
    data = _load(profile_path)
    if data is None:
        return {"exists": False, "fields": [], "unanswered": []}
    out, unanswered = [], []
    for f in FIELDS:
        value = (data.get(f["in"]) or {}).get(f["key"])
        if f["kind"] == "multi":
            value = [v for v in (value or []) if isinstance(v, str)] if isinstance(value, list) else []
        entry = {k: f[k] for k in ("key", "section", "label", "kind", "required") if k in f}
        entry.update({k: f[k] for k in ("options", "help", "placeholder", "default") if k in f})
        entry["value"] = value
        out.append(entry)
        if f["required"] and not _filled(value):
            unanswered.append(f["key"])
    return {"exists": True, "fields": out, "unanswered": unanswered}


def _clean(field: Dict[str, Any], raw: Any) -> Any:
    kind = field["kind"]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if str(raw).strip().lower() in ("yes", "true", "1"):
            return True
        if str(raw).strip().lower() in ("no", "false", "0"):
            return False
        raise AboutYouError(f'Answer Yes or No for "{field["label"]}".')
    if kind == "multi":
        if not isinstance(raw, list):
            raise AboutYouError(f'Pick at least one for "{field["label"]}".')
        picked = [v for v in LEVELS if v in raw]
        if field["required"] and not picked:
            raise AboutYouError(f'Pick at least one for "{field["label"]}".')
        return picked
    text = str(raw if raw is not None else "").strip()[:200]
    if field["required"] and not text:
        raise AboutYouError(f'Answer "{field["label"]}".')
    return text


def save_about_you(profile_path: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    """Writes the answers into the profile. Only known questions are accepted; everything else in the file stays as it was."""
    data = _load(profile_path)
    if data is None:
        raise AboutYouError("Create your profile from a resume first, then answer these.")
    if not isinstance(answers, dict):
        raise AboutYouError("The answers were not valid.")
    for key, raw in answers.items():
        field = SPEC.get(key)
        if field is None:
            continue                                   # an unknown key is ignored, never written
        value = _clean(field, raw)
        if field["kind"] == "text" and not value:
            data.setdefault(field["in"], {}).pop(key, None)
        else:
            data.setdefault(field["in"], {})[key] = value
    tmp = profile_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, profile_path)
    try:
        os.chmod(profile_path, 0o600)
    except OSError:
        pass
    return {"saved": [k for k in answers if k in SPEC]}
