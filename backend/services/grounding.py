"""Grounding: every answer typed into a job form must come from the user's own data.

A language model asked to fill a form will happily make things up: a number of years, a skill, a degree date, a paragraph about why it
loves the company. Prompts asking it not to are not a guarantee. This module is the guarantee, in two parts that need no model:

* `ProfileFacts.answer(question, options)` looks a question up in the profile (and the user's saved answers) with plain rules and
  returns the answer *and where it came from*, or says there is no data. "No data" is never turned into "No": not listing a skill is not
  the same as not having it.
* `ProfileFacts.check(answers)` takes what the agent is about to submit and flags every answer that cannot be traced to the profile:
  a number that is nowhere in the profile, a company the user never worked for, a yes about a skill the user never listed.

The browser agent gets both as tools (see browser_use_tools.py). The same code is used by the tests and by the bench."""
from __future__ import annotations

import datetime
import difflib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

PREFER_NOT = "Prefer not to say"
DECLINE_OPTION = re.compile(r"prefer not|decline|do not wish|don'?t wish|not to (?:say|disclose|answer|identify)|rather not|choose not", re.I)
YES_WORDS = re.compile(r"^(yes|y|true|i am|i do|i have|i can|i will|authori[sz]ed)\b", re.I)
NO_WORDS = re.compile(r"^(no|n|false|i am not|i do not|i don'?t|i have not|not authori[sz]ed)\b", re.I)

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE = re.compile(r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?((?:19|20)\d{2})", re.I)
_PRESENT = re.compile(r"present|current|now|ongoing|today", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


# ── text helpers ─────────────────────────────────────────────────────────────────
def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#.@/%£$ -]", " ", str(text or "").lower())).strip()


def _walk(value: Any, key: str = "") -> Iterable[str]:
    """Every string in a profile, except secrets."""
    if "password" in key.lower() or key.lower() in ("user_id", "portals_password"):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v, key)
    elif isinstance(value, bool):
        return
    elif isinstance(value, (str, int, float)) and str(value).strip():
        yield str(value)


def _month_index(match: "re.Match[str]", end: bool = False) -> int:
    month = MONTHS.get((match.group(1) or "").lower()[:3], 12 if end else 1)
    return int(match.group(2)) * 12 + month


def parse_span(text: str, today: Optional[datetime.date] = None) -> Optional[Tuple[int, int]]:
    """'Dec 2024 - Aug 2026' -> (start, end) as month numbers, or None. A future end is cut to today; 'Present' means today."""
    today = today or datetime.date.today()
    now = today.year * 12 + today.month
    text = str(text or "")
    found = list(_DATE.finditer(text))
    if not found:
        return None
    start = _month_index(found[0])
    if len(found) > 1:
        end = _month_index(found[-1], end=True)
    elif _PRESENT.search(text[found[0].end():]):
        end = now
    else:
        end = start
    end = min(end, now)
    return (start, end) if end >= start else None


def merge_months(spans: List[Tuple[int, int]]) -> int:
    """Total months covered by overlapping spans, counting each month once."""
    total, last_end = 0, None
    for start, end in sorted(spans):
        if last_end is None or start > last_end:
            total += end - start
            last_end = end
        elif end > last_end:
            total += end - last_end
            last_end = end
    return total


def years_phrase(months: int) -> str:
    years, rest = divmod(months, 12)
    parts = ([f"{years} year{'s' if years != 1 else ''}"] if years else []) + ([f"{rest} month{'s' if rest != 1 else ''}"] if rest else [])
    return " ".join(parts) or "less than a month"


# ── options ──────────────────────────────────────────────────────────────────────
def pick_option(answer: str, options: Optional[List[str]]) -> Optional[str]:
    """The option that best says the same thing as `answer`, or None. Never invents an option."""
    options = [str(o) for o in (options or []) if str(o).strip()]
    if not options or not str(answer).strip():
        return None
    target = norm(answer)
    for o in options:
        if norm(o) == target:
            return o
    if DECLINE_OPTION.search(answer):
        return next((o for o in options if DECLINE_OPTION.search(o)), None)
    if YES_WORDS.match(answer.strip()) and len(target) < 12:
        yes = [o for o in options if YES_WORDS.match(o.strip())]
        if yes:
            return yes[0]
    if NO_WORDS.match(answer.strip()) and len(target) < 12:
        no = [o for o in options if NO_WORDS.match(o.strip())]
        if no:
            return no[0]
    contained = [o for o in options if target and (target in norm(o) or norm(o) in target) and len(norm(o)) > 1]
    if len(contained) == 1:
        return contained[0]
    close = difflib.get_close_matches(target, [norm(o) for o in options], n=1, cutoff=0.72)
    return next((o for o in options if norm(o) == close[0]), None) if close else None


# ── what the questions mean ──────────────────────────────────────────────────────
def _re(pattern: str) -> "re.Pattern[str]":
    return re.compile(pattern, re.I)


INTENTS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("over_18", _re(r"\bover (the age of )?(18|eighteen)\b|\b(18|eighteen)\+|\b(18|eighteen)\b.*\b(older|over|years|age)|\b(at least|minimum) (age|18)|legal working age|over the age")),
    ("background_check", _re(r"background (check|screen|investigation)|criminal (record|history|conviction)|drug (test|screen)|consent to .*(check|screening)")),
    ("worked_here_before", _re(r"(previously|ever|before).{0,40}(work|employ).{0,40}(for|at|with)|worked (for|at|with) .* before|former employee|current employee")),
    ("sponsorship", _re(r"sponsor")),
    ("work_authorization", _re(r"(authori[sz]ed|eligible|right|permit|legally|entitled).{0,40}work|work (permit|authori[sz]ation|eligibility|rights?)|visa status|immigration status")),
    ("notice_period", _re(r"notice period|how much notice|start date|when can you start|available to start|earliest (start|available)|availability to start|date available")),
    ("salary", _re(r"salary|compensation|pay (expectation|range|requirement)|expected pay|desired (pay|rate)|rate expectation|remuneration")),
    ("relocation", _re(r"relocat")),
    ("work_arrangement", _re(r"(remote|hybrid|on-?site|in-?office|work arrangement|work location preference)")),
    ("referral_source", _re(r"how did you (hear|find|learn)|where did you (hear|find|learn)|source of (application|referral)|referred by")),
    ("pronouns", _re(r"pronoun")),
    ("preferred_name", _re(r"preferred (first )?name|nickname|name you go by|goes by")),
    ("gender", _re(r"\bgender\b|\bsex\b")),
    ("sexual_orientation", _re(r"sexual orientation")),
    ("transgender", _re(r"transgender|trans\b")),
    ("ethnicity", _re(r"ethnic|race\b|racial|hispanic|latino")),
    ("veteran", _re(r"veteran|military|armed forces")),
    ("disability", _re(r"disabilit")),
    ("first_name", _re(r"\b(first|given) name\b|forename")),
    ("last_name", _re(r"\b(last|family) name\b|surname")),
    ("email", _re(r"e-?mail")),
    ("phone", _re(r"phone|mobile|telephone|cell\b|contact number")),
    ("linkedin", _re(r"linkedin")),
    ("github", _re(r"github|git hub")),
    ("portfolio", _re(r"portfolio|personal (website|site)|\bwebsite\b|\bwebsite url\b|other (link|url)")),
    ("postcode", _re(r"post ?code|postal|zip")),
    ("country", _re(r"\bcountry\b|nationality|citizen")),
    ("city", _re(r"\bcity\b|\btown\b|where (are you|do you) (based|located|live)|current location|\blocation\b|\bresid")),
    ("current_company", _re(r"current (company|employer|organi[sz]ation)|present employer|most recent (company|employer)|employer name|company name")),
    ("current_title", _re(r"current (job |role |position )?title|most recent (job |role )?title|present (role|position)|job title|position held")),
    ("currently_employed", _re(r"currently (employed|working)|are you employed")),
    ("years_experience", _re(r"years?.{0,30}(of )?(experience|exp)|experience.{0,30}years|how many years|length of experience")),
    ("degree", _re(r"\bdegree\b|level of education|highest (level of )?(education|qualification)|qualification")),
    ("school", _re(r"school|university|college|institution|alma mater")),
    ("field_of_study", _re(r"field of study|major\b|subject|discipline|course of study")),
    ("graduation_date", _re(r"graduat|completion date|date completed|year of (graduation|completion)|end date.*(study|education)")),
    ("gpa", _re(r"\bgpa\b|\bcgpa\b|grade point|grade average|\bgrade\b|class of degree|degree classification")),
    ("languages", _re(r"language")),
    ("skill_experience", _re(r"(experience|proficien|familiar|skill|knowledge|worked|expertise|comfortable).{0,40}\b(with|in|using|of)\b|do you (have|know|use)")),
    ("full_name", _re(r"\bfull name\b|\bname\b|legal name")),
]

OPEN_ENDED = _re(r"why (do|would|are) you|why us|tell us (about|more)|describe|explain|what (makes|interests|excites|motivates)|motivation|cover letter|additional information|anything else|about yourself|strengths?|weakness|achievement|proud|challenge")


def classify(question: str) -> str:
    """The kind of question this is ('sponsorship', 'years_experience', ...), 'open_ended' for essays, or 'unknown'."""
    text = str(question or "")
    for key, pattern in INTENTS:
        if pattern.search(text):
            return key
    return "open_ended" if OPEN_ENDED.search(text) else "unknown"


def _skill_in(question: str) -> str:
    """The thing a skill question asks about: 'Do you have experience with Kubernetes?' -> 'kubernetes'."""
    m = re.search(r"(?:experience|proficien\w*|familiar\w*|knowledge|expertise|skills?|worked|comfortable)\W+(?:\w+\W+){0,3}?(?:with|in|using|of|on)\s+([A-Za-z0-9+#.\- /]{2,40}?)(?:\?|\.|,|$| \(| and/or)", question, re.I) \
        or re.search(r"do you (?:have|know|use)\s+(?:any |some )?(?:experience (?:with|in|using) )?([A-Za-z0-9+#.\- /]{2,40}?)(?:\?|\.|,|$| \()", question, re.I) \
        or re.search(r"years?.{0,25}?(?:experience )?(?:with|in|using|of)\s+([A-Za-z0-9+#.\- /]{2,40}?)(?:\?|\.|,|$| \()", question, re.I)
    skill = norm(m.group(1)) if m else ""
    return "" if re.search(r"\b(you|have|experience|years?|total|overall|work|professional|relevant|industry)\b", skill) else skill


class ProfileFacts:
    """The user's data, ready to be asked questions."""

    def __init__(self, resume_data: Dict[str, Any], saved_answers: Optional[List[Dict[str, str]]] = None, today: Optional[datetime.date] = None):
        data = dict(resume_data or {})
        cand = dict(data.get("candidate")) if isinstance(data.get("candidate"), dict) else {}
        merged = {**{k: v for k, v in data.items() if k != "candidate"}, **cand}
        self.c: Dict[str, Any] = merged
        self.prefs: Dict[str, Any] = data.get("search_preferences") if isinstance(data.get("search_preferences"), dict) else {}
        self.saved = [a for a in (saved_answers or []) if isinstance(a, dict) and a.get("question") and a.get("answer")]
        self.today = today or datetime.date.today()
        self._corpus = norm(" ".join(list(_walk(merged)) + [a["answer"] for a in self.saved]))
        self.work = [w for w in (merged.get("work_experience") or []) if isinstance(w, dict)]
        self.education = [e for e in (merged.get("education") or []) if isinstance(e, dict)]

    # ── small getters ────────────────────────────────────────────────────────────
    def _text(self, *keys: str) -> str:
        for key in keys:
            value = self.c.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
                return str(value).strip()
        return ""

    def _name_parts(self) -> Tuple[str, str]:
        full = self._text("name", "full_name")
        parts = full.split()
        return (parts[0], " ".join(parts[1:])) if len(parts) > 1 else (full, "")

    def _role_text(self, role: Dict[str, Any]) -> str:
        return norm(" ".join(_walk(role)))

    def _role_span(self, role: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        return parse_span(str(role.get("timeline") or role.get("dates") or role.get("period") or "") or f"{role.get('start', '')} - {role.get('end', '')}", self.today)

    def total_months(self) -> int:
        return merge_months([s for s in (self._role_span(w) for w in self.work) if s])

    def skill_months(self, skill: str) -> int:
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])")
        return merge_months([s for w in self.work if pattern.search(self._role_text(w)) for s in [self._role_span(w)] if s])

    def has_skill(self, skill: str) -> bool:
        return bool(skill) and bool(re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", self._corpus))

    def in_corpus(self, text: str) -> bool:
        needle = norm(text)
        return len(needle) >= 2 and needle in self._corpus

    # ── the resolver ─────────────────────────────────────────────────────────────
    def answer(self, question: str, options: Optional[List[str]] = None, company: Optional[str] = None) -> Dict[str, Any]:
        """{status, answer, option, source, note}. status is 'answer', 'policy' (a safe standard reply), 'compose' (write from the given
        facts only), 'no_data' (do not type anything) or 'stop' (a question only the user may answer)."""
        intent = classify(question)
        out = self._resolve(intent, question, company)
        if out["status"] in ("answer", "policy") and options:
            picked = pick_option(out["answer"], options)
            out["option"] = picked
            if picked is None:
                out["note"] = (out.get("note", "") + " None of the listed options matches this answer. Pick the closest honest option, or if there is none, leave it and report it.").strip()
        out.setdefault("option", None)
        out["intent"] = intent
        saved = self._saved_match(question)
        if saved and out["status"] in ("no_data", "compose"):          # the user's own written answer beats a gap or a draft
            out.update(status="answer", answer=saved["answer"], source="saved_answers", note="Your saved answer. Type it exactly as written.")
            out["option"] = pick_option(saved["answer"], options) if options else None
        return out

    def _saved_match(self, question: str) -> Optional[Dict[str, str]]:
        target = norm(question)
        best, score = None, 0.0
        for item in self.saved:
            s = difflib.SequenceMatcher(None, target, norm(item["question"])).ratio()
            words = set(target.split()) & set(norm(item["question"]).split())
            s = max(s, len(words) / max(1, len(set(norm(item["question"]).split()))) if len(words) >= 3 else 0)
            if s > score:
                best, score = item, s
        return best if score >= 0.72 else None

    def _ans(self, value: Any, source: str, note: str = "", status: str = "answer") -> Dict[str, Any]:
        return {"status": status, "answer": str(value), "source": source, "note": note}

    def _none(self, why: str) -> Dict[str, Any]:
        return {"status": "no_data", "answer": None, "source": "", "note": why + " Do not guess and do not type anything. If the field is required, stop and report this question as needing the user."}

    def _stop(self, why: str) -> Dict[str, Any]:
        return {"status": "stop", "answer": None, "source": "", "note": why}

    def _resolve(self, intent: str, question: str, company: Optional[str]) -> Dict[str, Any]:
        c = self.c
        if intent in ("first_name", "last_name", "full_name"):
            first, last = self._name_parts()
            value = {"first_name": first, "last_name": last, "full_name": self._text("name", "full_name")}[intent]
            return self._ans(value, "candidate.name") if value else self._none("The profile has no name for this.")
        direct = {"email": "email", "phone": "phone", "linkedin": "linkedin", "github": "github", "portfolio": "portfolio", "postcode": "postal_code",
                  "preferred_name": "preferred_name", "pronouns": "pronouns", "languages": "languages", "salary": "salary_expectations",
                  "notice_period": "notice_period", "relocation": "relocation", "referral_source": "referral_source"}
        if intent == "salary":
            value = self._text("salary_expectations")
            return self._ans(value, "candidate.salary_expectations") if value else self._ans("Open to discussion", "policy", "No salary given in the profile. This states no number.", "policy")
        if intent == "referral_source":
            value = self._text("referral_source")
            return self._ans(value, "candidate.referral_source") if value else self._ans("the site where you found this job", "policy", "Name the site you found the job on (LinkedIn, Indeed, the careers page). That is a fact you know.", "policy")
        if intent in direct:
            value = self._text(direct[intent])
            return self._ans(value, "candidate." + direct[intent]) if value else self._none(f"The profile has no {intent.replace('_', ' ')}.")
        if intent == "work_arrangement":
            arr = c.get("work_arrangement")
            return self._ans(", ".join(arr), "candidate.work_arrangement") if isinstance(arr, list) and arr else self._none("The profile does not say where you want to work.")
        if intent == "city":
            return self._ans(self._text("location"), "candidate.location") if self._text("location") else self._none("The profile has no location.")
        if intent == "country":
            value = self._text("citizenship") if re.search(r"nationality|citizen", question, re.I) else (self._text("country") or (self._text("location").split(",")[-1].strip() if "," in self._text("location") else ""))
            return self._ans(value, "candidate.citizenship" if re.search(r"nationality|citizen", question, re.I) else "candidate.location") if value else self._none("The profile has no country.")
        if intent == "sponsorship":
            need = c.get("requires_sponsorship")
            return self._ans("Yes" if need else "No", "candidate.requires_sponsorship") if isinstance(need, bool) else self._none("You have not said whether you need visa sponsorship.")
        if intent == "work_authorization":
            text, need = self._text("work_authorization").lower(), c.get("requires_sponsorship")
            if re.search(r"allows? me to work|authori[sz]ed|right to work|citizen", text) and "need" not in text:
                return self._ans("Yes", "candidate.work_authorization", self._text("work_authorization"))
            if re.search(r"\bneed\b.*(visa|sponsor)|not authori[sz]ed|require", text):
                return self._ans("No", "candidate.work_authorization", self._text("work_authorization"))
            return self._none("The profile does not say clearly whether you are authorised to work here.")
        if intent in ("gender", "ethnicity", "veteran", "disability", "sexual_orientation", "transgender"):
            key = {"veteran": "veteran_status", "disability": "disability_status"}.get(intent, intent)
            value = self._text(key)
            if value:
                return self._ans(value, "candidate." + key)
            return self._ans(PREFER_NOT, "policy", "You have not answered this, so the agent declines to answer. Choose the 'prefer not to say' option.", "policy")
        if intent in ("over_18", "background_check"):
            if intent == "over_18":
                value = c.get("over_18")
                return self._ans("Yes" if value else "No", "candidate.over_18") if isinstance(value, bool) else self._stop("Only you can answer the age question. Stop and report it.")
            consent = self._text("background_check_consent")
            return self._ans("Yes", "candidate.background_check_consent") if consent.lower().startswith("yes") else self._stop("Consent to a check is a legal agreement only you can give. Stop and report it.")
        if intent == "worked_here_before":
            names = [norm(w.get("company")) for w in self.work if w.get("company")]
            if not company:
                return self._none("Say which company this application is for (the company argument) to answer this.")
            return self._ans("Yes" if any(n and (n in norm(company) or norm(company) in n) for n in names) else "No", "candidate.work_experience", "Answered from the companies in your work history only.")
        if intent in ("current_company", "current_title", "currently_employed"):
            if not self.work:
                return self._none("The profile has no work history.")
            latest = max(self.work, key=lambda w: (self._role_span(w) or (0, 0))[1])
            span = self._role_span(latest)
            ongoing = bool(span and span[1] >= self.today.year * 12 + self.today.month) or bool(_PRESENT.search(str(latest.get("timeline") or latest.get("dates") or "")))
            if intent == "currently_employed":
                return self._ans("Yes" if ongoing else "No", "candidate.work_experience")
            value = latest.get("company") if intent == "current_company" else (latest.get("role") or latest.get("title"))
            note = "" if ongoing else "This is your most recent job; the profile shows it has ended."
            return self._ans(value, "candidate.work_experience[latest]", note) if value else self._none("The latest job has no " + ("company" if intent == "current_company" else "title") + ".")
        if intent in ("degree", "school", "field_of_study", "graduation_date", "gpa"):
            if not self.education:
                return self._none("The profile has no education.")
            keys = {"degree": ("degree",), "school": ("institution", "school", "university"), "field_of_study": ("field", "major"),
                    "graduation_date": ("timeline", "end", "graduation"), "gpa": ("cpi", "gpa", "grade")}[intent]
            done = [e for e in self.education if not (self._role_span_education(e) or (0, 10 ** 9))[1] > self.today.year * 12 + self.today.month] or self.education
            entry = done[0] if intent != "degree" else done[0]
            value = next((str(entry[k]) for k in keys if entry.get(k)), "")
            if intent == "graduation_date" and value:
                spans = list(_DATE.finditer(value))
                value = (spans[-1].group(0) if spans else value)
            if intent == "gpa" and value:
                value = re.sub(r"(?i)^(cgpa|gpa|cpi)\s*[:\-]?\s*", "", value)
            return self._ans(value, "candidate.education[0]", "From your first completed education entry." if len(self.education) > 1 else "") if value else self._none(f"The profile has no {intent.replace('_', ' ')}.")
        if intent == "years_experience":
            skill = _skill_in(question)
            if skill:
                months = self.skill_months(skill)
                if months:
                    return self._ans(max(1, months // 12) if months >= 12 else "Less than 1", "candidate.work_experience", f"{years_phrase(months)} in roles that mention {skill}.")
                return self._none(f"The profile does not show how long you worked with {skill}.")
            months = self.total_months()
            return self._ans(months // 12 if months >= 12 else "Less than 1", "candidate.work_experience", f"{years_phrase(months)} of dated work experience in total.") if months else self._none("The work history has no dates to count.")
        if intent == "skill_experience":
            skill = _skill_in(question)
            if not skill:
                return self._none("Could not tell which skill is being asked about.")
            return self._ans("Yes", "candidate.skills", f"{skill} appears in your profile.") if self.has_skill(skill) else self._none(f"{skill} is not in your profile. Not listing a skill does not mean you lack it, so this is not answered No.")
        if intent == "open_ended":
            return {"status": "compose", "answer": None, "source": "candidate", "option": None,
                    "note": "Write this ONLY from these facts, in plain first person, with no number, employer, tool or claim that is not listed.",
                    "facts": self.writing_facts()}
        return self._none("This question is not covered by the profile.")

    def _role_span_education(self, entry: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        return parse_span(str(entry.get("timeline") or entry.get("dates") or ""), self.today) or None

    def writing_facts(self) -> Dict[str, Any]:
        """What a free-text answer may draw on."""
        return {"summary": self._text("experience_summary", "summary"), "roles": [
            {"company": w.get("company"), "role": w.get("role") or w.get("title"), "timeline": w.get("timeline"), "highlights": (w.get("highlights") or [])[:4]} for w in self.work[:4]],
            "education": [{"institution": e.get("institution"), "degree": e.get("degree")} for e in self.education[:3]], "skills": list(self.c.get("core_skills") or [])[:25],
            "projects": [{"title": p.get("title"), "description": p.get("description")} for p in (self.c.get("projects") or []) if isinstance(p, dict)][:3]}

    # ── checking what is about to be submitted ───────────────────────────────────
    def check(self, answers: List[Dict[str, Any]], company: Optional[str] = None) -> List[Dict[str, str]]:
        """Problems in what the agent typed. Empty means every answer can be traced to the profile or a safe standard reply."""
        problems: List[Dict[str, str]] = []
        for item in answers or []:
            question, given = str(item.get("question", "")), str(item.get("answer", "")).strip()
            if not given:
                continue
            resolved = self.answer(question, None, company)
            why = self._why_ungrounded(resolved, given)
            if why:
                problems.append({"question": question[:160], "answer": given[:160], "problem": why})
        return problems

    def _why_ungrounded(self, resolved: Dict[str, Any], given: str) -> str:
        status, expected = resolved["status"], resolved.get("answer")
        if status == "stop":
            return "Only the user can answer this. Remove it and report the question."
        if status in ("answer", "policy") and expected is not None:
            if self._same(expected, given) or self.in_corpus(given):
                return ""
            if resolved.get("intent") in ("referral_source",) or status == "policy":
                return "" if status == "policy" and resolved.get("intent") != "salary" else ("" if self._same(expected, given) else "The profile says " + str(expected)[:80] + ".")
            return f"The profile says {str(expected)[:80]}, not this."
        # no data or free text: the answer must be built from what the profile contains
        return self._free_text_problem(given)

    def _same(self, expected: Any, given: str) -> bool:
        a, b = norm(expected), norm(given)
        return bool(a) and (a == b or a in b and len(b) <= len(a) + 12 or b in a and len(b) >= 2)

    def _free_text_problem(self, text: str) -> str:
        """For text the resolver cannot give: every number and every capitalised name in it must exist in the profile."""
        if self.in_corpus(text):
            return ""
        if norm(text) in ("yes", "no", "n/a", "na", "none") or DECLINE_OPTION.search(text):
            return ""
        for number in _NUMBER.findall(text):
            if number not in self._corpus and number.replace(",", "") not in self._corpus.replace(",", ""):
                return f"The number {number} is not in your profile."
        for name in set(re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z0-9&]{2,}(?:\s+[A-Z][a-zA-Z0-9&]{2,})*)", text)):
            if norm(name) not in self._corpus and norm(name) not in ("linkedin", "indeed", "greenhouse", "lever", "ashby", "workday"):
                return f'"{name}" is not in your profile.'
        return ""
