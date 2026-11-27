"""Plain rules that decide whether a job is worth applying to, before the agent spends a browser run on it.

Three checks, each with a reason a person can read: the seniority in the title against the levels the user wants, the
job's place against the places the user wants, and a "we do not sponsor visas" line against a user who needs one.
No AI is involved, so the same job always gets the same answer."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

LEVEL_WORDS = {
    "intern": r"\b(intern|internship|placement|trainee|apprentice|work experience)\b",
    "junior": r"\b(junior|jr\.?|graduate|entry[- ]level|associate)\b",
    "senior": r"\b(senior|sr\.?)\b",
    "staff": r"\b(staff|principal|distinguished)\b",
    "lead": r"\b(lead|team lead|tech lead)\b",
    "management": r"\b(manager|director|head of|vice president|vp|chief|cto|ceo)\b",
}
PREFERENCE_ALIASES = {
    "intern": "intern", "internship": "intern", "placement": "intern", "trainee": "intern",
    "junior": "junior", "entry": "junior", "entry-level": "junior", "entry level": "junior", "graduate": "junior", "associate": "junior",
    "senior": "senior", "sr": "senior", "staff": "staff", "principal": "staff", "lead": "lead",
    "manager": "management", "director": "management", "head": "management", "executive": "management", "management": "management",
}
NO_SPONSORSHIP = re.compile(
    r"(unable to (?:offer |provide )?(?:visa )?sponsor|(?:do(?:es)? not|don't|cannot|can't|will not|won't) (?:offer |provide )?(?:visa )?sponsor|"
    r"no (?:visa )?sponsorship|without (?:the need for )?(?:visa )?sponsorship|not (?:able|in a position) to (?:offer |provide )?(?:visa )?sponsor|"
    r"must (?:already )?have the (?:full )?right to work|must be (?:legally )?(?:authori[sz]ed|eligible) to work)", re.I)
COUNTRY_ALIASES = {
    "uk": {"uk", "united kingdom", "england", "scotland", "wales", "great britain", "gb"},
    "us": {"us", "usa", "united states"},
}


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;\n]", value) if v.strip()]
    if isinstance(value, Iterable):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def wanted_levels(prefs: Dict[str, Any]) -> set:
    """The levels the user wants. Besides the "seniority" list, a level named in the title filter or in the roles to search counts
    too: someone who searches for "AI Engineer Intern" and requires "Intern" in the title wants interns, whatever the list says."""
    chosen = {PREFERENCE_ALIASES[w.lower()] for w in _as_list(prefs.get("seniority")) if w.lower() in PREFERENCE_ALIASES}
    if not chosen:
        return chosen                               # no preference at all: no rule
    named = _as_list(prefs.get("required_title_keywords")) + _as_list(prefs.get("target_roles"))
    for level, pattern in LEVEL_WORDS.items():
        if any(re.search(pattern, text, re.I) for text in named):
            chosen.add(level)
    return chosen


def level_check(title: str, prefs: Dict[str, Any]) -> Tuple[bool, str]:
    wanted = wanted_levels(prefs)
    if not wanted:
        return True, ""
    for level, pattern in LEVEL_WORDS.items():
        if level not in wanted and re.search(pattern, title or "", re.I):
            return False, f"the title points to a {level} role, outside the levels you chose"
    return True, ""


def _places(text: str) -> set:
    tokens = {t.strip().lower() for t in re.split(r"[,/|;()\-]| or ", text or "") if t.strip()}
    for group in COUNTRY_ALIASES.values():
        if tokens & group:
            tokens |= group
    return tokens


def location_check(job_location: str, prefs: Dict[str, Any]) -> Tuple[bool, str]:
    wanted = _as_list(prefs.get("target_locations"))
    if not wanted or not (job_location or "").strip():
        return True, ""
    here = (job_location or "").lower()
    wanted_tokens = set().union(*[_places(w) for w in wanted])
    if "remote" in wanted_tokens and "remote" in here:
        return True, ""
    if any(token and token != "remote" and token in here for token in wanted_tokens):
        return True, ""
    if _places(job_location) & wanted_tokens:
        return True, ""
    return False, f"the job is in {job_location.strip()}, not in {', '.join(wanted)}"


def sponsorship_check(jd_text: str, candidate: Dict[str, Any]) -> Tuple[bool, str]:
    needs = candidate.get("requires_sponsorship")
    if isinstance(needs, str):
        needs = needs.strip().lower() in ("yes", "true", "1", "required")
    if not needs:
        return True, ""
    match = NO_SPONSORSHIP.search(jd_text or "")
    if match:
        return False, f"it says \"{match.group(0).strip()}\" and you need sponsorship"
    return True, ""


def check_relevance(job: Dict[str, Any], jd_text: str, candidate: Dict[str, Any], prefs: Dict[str, Any]) -> Tuple[bool, str]:
    """(True, "") when the job is a fit, else (False, reason)."""
    for ok, reason in (
        level_check(str(job.get("title") or job.get("job_title") or ""), prefs),
        location_check(str(job.get("location") or ""), prefs),
        sponsorship_check(jd_text, candidate),
    ):
        if not ok:
            return False, reason
    return True, ""
