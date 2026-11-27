"""
job_level.py - which bucket does a job belong to, and how many years of experience does it ask for?

    intern        internships, placements, year-in-industry, summer analyst ...
    graduate      graduate schemes, junior / entry-level / early-careers roles, apprenticeships, roles asking <= 1 year
    experienced   everything else (mid, senior, lead ...), with the years of experience the posting asks for

The TITLE decides first (it is the clearest signal). Only when the title is neutral ("Security Engineer") is the job
description read: the years of experience it asks for decide between graduate (0-1 years) and experienced (2+ years).
No LLM is used, so classifying hundreds of postings is instant and free.
"""

import re
from dataclasses import dataclass
from typing import Optional

try:
    from .role_spec import LEVELS, _SENIOR_TITLE, _compile
except ImportError:  # pragma: no cover
    from role_spec import LEVELS, _SENIOR_TITLE, _compile

BUCKETS = ("intern", "graduate", "experienced")
_INTERN_RE = _compile(LEVELS["intern"]["terms"] + ["student", "year in industry", "industrial placement", "work experience placement"])
_GRAD_RE = _compile(LEVELS["graduate"]["terms"] + ["apprentice", "apprenticeship", "apprentices", "school leaver", "graduate programme",
                                                    "graduate program", "campus", "new starter"])
_SENIOR_TAGS = (("principal", "Principal"), ("staff", "Staff"), ("head of", "Head"), ("director", "Director"), ("vp", "VP"),
                ("vice president", "VP"), ("lead", "Lead"), ("senior", "Senior"), ("sr", "Senior"), ("manager", "Manager"))

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(\d{1,2}|" + "|".join(_WORDS) + r")"
_RANGE = re.compile(rf"{_NUM}\s*(?:\+|plus)?\s*(?:-|–|—|to)\s*{_NUM}\s*\+?\s*years?", re.I)
_PLUS = re.compile(rf"{_NUM}\s*(?:\+|plus)\s*years?", re.I)
_ATLEAST = re.compile(rf"(?:at least|minimum(?: of)?|min\.?|over|more than)\s*{_NUM}\s*years?", re.I)
_PLAIN = re.compile(rf"{_NUM}\s*years?\b", re.I)
_CONTEXT = re.compile(r"experience|working|background|track record|hands[- ]on|professional|industry|in a similar role|in a (?:similar|related)", re.I)
_NO_EXP = re.compile(r"no (?:prior |previous |commercial )?experience (?:is )?(?:required|necessary|needed)|"
                     r"(?:don't|do not|doesn't) need (?:any )?(?:prior )?experience|no experience needed|(?<![\d.])0 years", re.I)
_ENTRY_CUES = re.compile(r"graduate|entry[- ]level|early career|recent graduate|new grad|junior|trainee|no experience|"
                         r"final[- ]year|recently graduated|first (?:role|job)", re.I)


def _n(x: str) -> int:
    x = x.lower()
    return _WORDS.get(x, int(x) if x.isdigit() else 0)


@dataclass
class Level:
    bucket: str                      # intern | graduate | experienced
    years_min: Optional[int]         # None = the posting does not say
    years_max: Optional[int]
    years_label: str                 # "3+", "3-5", "0", "not stated" ("" for interns)
    tag: str                         # Senior / Lead / Mid / Junior / ... (free text for the sheet)
    reason: str


def years_required(text: str):
    """(min, max, label) of the years of experience a posting asks for. (None, None, 'not stated') if it doesn't say."""
    text = text or ""
    if _NO_EXP.search(text):
        return 0, 0, "0"
    found = []                       # (min, max)
    for m in _RANGE.finditer(text):
        window = text[max(0, m.start() - 80): m.end() + 80]
        if _CONTEXT.search(window):
            found.append((_n(m.group(1)), _n(m.group(2))))
    for rx in (_PLUS, _ATLEAST, _PLAIN):
        for m in rx.finditer(text):
            window = text[max(0, m.start() - 80): m.end() + 80]
            if not _CONTEXT.search(window):
                continue
            n = _n(m.group(1))
            if 0 < n <= 15 and not any(a <= n <= (b or a) for a, b in found):
                found.append((n, None))
    if not found:
        return None, None, "not stated"
    # The headline requirement is the first one stated in the text; later ones are usually per-skill.
    lo, hi = found[0]
    lo = min(lo, 15)
    if hi:
        return lo, hi, f"{lo}-{hi}"
    return lo, None, f"{lo}+" if lo else "0"


def _tag(title: str) -> str:
    t = (title or "").lower()
    for word, tag in _SENIOR_TAGS:
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", t):
            return tag
    if re.search(r"(?<![a-z])(junior|jr|graduate|entry)(?![a-z])", t):
        return "Junior"
    return "Mid"


def classify(title: str, description: str = "") -> Level:
    """Bucket + years of experience for one posting."""
    title = title or ""
    description = description or ""
    lo, hi, label = years_required(description)
    if _INTERN_RE and _INTERN_RE.search(title):
        return Level("intern", None, None, "", "Intern", "title says intern/placement")
    if _GRAD_RE and _GRAD_RE.search(title):
        return Level("graduate", lo, hi, label if description else "", "Junior", "title says graduate/junior/early careers")
    if _SENIOR_TITLE.search(title):
        return Level("experienced", lo, hi, label, _tag(title), "senior-level title")
    # A neutral title: the description decides.
    if lo is not None:
        if lo <= 1:
            return Level("graduate", lo, hi, label, "Junior", f"asks for {label} years")
        return Level("experienced", lo, hi, label, _tag(title), f"asks for {label} years")
    if description and _ENTRY_CUES.search(description[:700]):
        return Level("graduate", None, None, "not stated", "Junior", "description mentions graduate/entry-level")
    return Level("experienced", None, None, "not stated", _tag(title), "no early-career signal in the title" if not description else
                 "no years stated and no early-career wording")
