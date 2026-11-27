"""
fit_scorer.py - evidence-based job fit scoring (replaces the fixed keyword list for `scan` and `ats`).

How it works
1. An LLM reads the job description once and lists its real requirements (any field, not a fixed
   taxonomy). For each it gives a verdict against the candidate's profile (yes / partial / no) and
   quotes the profile evidence it relied on. It also flags hard knockouts (citizenship, clearance,
   enrolment status...) and may report a closing date, which must be quoted verbatim from the text.
2. The scores are plain arithmetic over those verdicts (see `score_from_analysis`), so they are
   explainable and re-tunable without another LLM call.
3. Results are cached (data/fit_cache.db) by profile + job text, so re-scans are free and stable.

If the LLM is unavailable (quota, offline, malformed answer) `analyze_fit` raises FitUnavailable and
callers fall back to the old keyword scorer, clearly labelled as such.

Only skills, experience, education, projects and work-eligibility facts are sent to the LLM. Contact
details and demographic fields (gender, ethnicity, veteran / disability status) are never included.
"""

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

PROMPT_VERSION = "v2"  # bump to invalidate cached analyses when the prompt changes
MAX_JD_CHARS = 7000
VERDICT_VALUE = {"yes": 1.0, "partial": 0.5, "no": 0.0}
GATE_CAP = 50  # max overall score when a "must" education requirement (degree level / enrolment) is not met
IMPORTANCE_WEIGHT = {"must": 3.0, "nice": 1.0}


class FitUnavailable(RuntimeError):
    """The LLM analysis could not be produced; use the keyword scorer instead."""


@dataclass
class FitResult:
    eligible: bool
    knockout_reason: Optional[str]
    skills_score: int
    experience_score: int
    role_fit: int
    overall: int
    matched: List[str]
    missing: List[str]
    summary: str
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    closing_date: Optional[date] = None
    from_cache: bool = False


# ─── candidate -> text ────────────────────────────────────────────────────────
def _timeline(item: dict) -> str:
    if item.get("timeline"):
        return str(item["timeline"])
    start, end = item.get("start_date"), item.get("end_date")
    return f"{start} - {end or 'Present'}" if start else ""


def _bullets(item: dict) -> List[str]:
    out: List[str] = []
    for key in ("highlights", "description", "bullet_points"):
        v = item.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [str(x) for x in v]
    return out


def candidate_profile_text(candidate: dict) -> str:
    """Compact, PII-free description of the candidate. Works for the profile or a parsed resume."""
    L: List[str] = [f"Today's date: {date.today().isoformat()}"]
    summary = candidate.get("experience_summary") or candidate.get("summary")
    if summary:
        L.append(f"SUMMARY: {summary}")

    edu = candidate.get("education") or []
    if edu:
        L.append("EDUCATION:")
        for e in edu:
            if not isinstance(e, dict):
                continue
            L.append(f"- {e.get('degree', '')}, {e.get('institution', '')} ({_timeline(e) or e.get('graduation_date', '')})"
                     + (f" {e.get('cpi')}" if e.get("cpi") else ""))
            L += [f"    * {b}" for b in _bullets(e)]

    exp = candidate.get("work_experience") or candidate.get("experience") or []
    if exp:
        L.append("WORK EXPERIENCE:")
        for e in exp:
            if not isinstance(e, dict):
                continue
            L.append(f"- {e.get('role') or e.get('title', '')} at {e.get('company', '')} ({_timeline(e)})")
            if e.get("technologies"):
                L.append(f"    technologies: {', '.join(map(str, e['technologies']))}")
            L += [f"    * {b}" for b in _bullets(e)]

    projects = candidate.get("projects") or []
    if projects:
        L.append("PROJECTS:")
        for p in projects:
            if isinstance(p, dict):
                tech = f" [{', '.join(map(str, p.get('technologies') or []))}]" if p.get("technologies") else ""
                L.append(f"- {p.get('title', '')}{tech}: {p.get('description', '')}")

    skills: List[str] = []
    for key in ("core_skills", "skills"):
        v = candidate.get(key)
        if isinstance(v, list):
            skills += [str(s) for s in v]
        elif isinstance(v, dict):
            for k, vals in v.items():
                skills += [str(k)] + ([str(x) for x in vals] if isinstance(vals, list) else [])
    for vals in (candidate.get("skill_categories") or {}).values():
        skills += [str(x) for x in vals]
    if skills:
        L.append("SKILLS: " + ", ".join(dict.fromkeys(skills)))

    facts = []
    for label, key in (("Location", "location"), ("Citizenship", "citizenship"),
                       ("Authorised to work in the UK", "work_authorization")):
        if candidate.get(key) not in (None, ""):
            facts.append(f"{label}: {candidate[key]}")
    if "requires_sponsorship" in candidate:
        facts.append(f"Needs visa sponsorship: {'yes' if candidate['requires_sponsorship'] else 'no'}")
    if facts:
        L.append("WORK ELIGIBILITY: " + "; ".join(facts))
    return "\n".join(L)


# ─── prompt + schema ──────────────────────────────────────────────────────────
def _build_prompt(profile_text: str, title: str, company: str, jd_text: str, level: Optional[str]) -> str:
    seeking = f"The candidate is seeking {level}-level roles. " if level and level != "any" else ""
    return f"""You are a strict, evidence-based recruiter screening one candidate against one job.
{seeking}Judge ONLY from the candidate profile below. Never assume skills or experience that are not stated.

Return JSON with:
- requirements: the 6-15 real requirements of this job (skills, tools, experience, education, enrolment status).
  Skip boilerplate (benefits, equal-opportunity text, company blurbs). For each:
    text: short label (max 10 words)
    importance: "must" if required/minimum/core to the role, "nice" if preferred/bonus
    category: "skill" (tools, methods, domain knowledge), "experience" (years, prior roles, projects),
              "education" (degree, course, enrolment/graduation status), or "other"
    verdict: "yes" only if the profile shows direct evidence; "partial" if adjacent or weaker evidence
             (e.g. job wants PyTorch, profile shows TensorFlow); otherwise "no"
    evidence: the profile fact you relied on (a short quote or paraphrase), or "" for "no"
  DEGREE LEVEL IS A GATE: if a requirement names a degree level or enrolment (PhD, MSc, BSc, "final-year student")
  and the candidate's current or completed degree is a DIFFERENT level, the verdict is "no", never "partial".
  Use "partial" only for the right level in a different subject. Judge the candidate's current enrolment
  from the profile dates and today's date.
- knockouts: hard eligibility conditions in the posting (citizenship, security clearance, no visa sponsorship,
  must already live in a specific place, must be enrolled/graduating in a specific year). For each:
    text: the condition
    blocks_candidate: true ONLY if the WORK ELIGIBILITY / profile facts clearly fail it
                      (a mismatched degree level, e.g. PhD-only for an MSc student, counts)
- role_fit: integer 0-100: how well the role matches the direction of the candidate's background and projects
- summary: one sentence (max 30 words) on why this is or is not a good fit
- closing_date: the application deadline ONLY if the text states one, as YYYY-MM-DD, else ""
- closing_date_quote: the exact words from the job text that state the deadline, else ""

JOB: {title} at {company}
JOB DESCRIPTION:
{jd_text[:MAX_JD_CHARS]}

CANDIDATE PROFILE:
{profile_text}
"""


def _schema():
    from pydantic import BaseModel

    class Requirement(BaseModel):
        text: str
        importance: str
        category: str
        verdict: str
        evidence: str

    class Knockout(BaseModel):
        text: str
        blocks_candidate: bool

    class FitAnalysis(BaseModel):
        requirements: List[Requirement]
        knockouts: List[Knockout]
        role_fit: int
        summary: str
        closing_date: str
        closing_date_quote: str

    return FitAnalysis


def _default_llm(prompt: str, schema=None) -> str:
    """Call Gemini with a structured-output schema (defaults to the job-fit schema)."""
    try:
        from services.gemini_client import generate_content_with_fallback
    except ImportError:
        from backend.services.gemini_client import generate_content_with_fallback
    return generate_content_with_fallback(prompt, schema or _schema())


# ─── cache ────────────────────────────────────────────────────────────────────
_db_lock = threading.Lock()


def _cache_path() -> str:
    try:
        try:
            from config.constants import resolve_workspace_root
        except ImportError:
            from backend.config.constants import resolve_workspace_root
        root = resolve_workspace_root()
    except Exception:
        root = os.getcwd()
    return os.path.join(root, "data", "fit_cache.db")


def _cache_get(key: str) -> Optional[dict]:
    try:
        with _db_lock, sqlite3.connect(_cache_path()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS fit (key TEXT PRIMARY KEY, created REAL, analysis TEXT)")
            row = db.execute("SELECT analysis FROM fit WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
    except Exception:
        return None


def _cache_put(key: str, analysis: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with _db_lock, sqlite3.connect(_cache_path()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS fit (key TEXT PRIMARY KEY, created REAL, analysis TEXT)")
            db.execute("INSERT OR REPLACE INTO fit VALUES (?,?,?)", (key, time.time(), json.dumps(analysis)))
    except Exception:
        pass


# ─── LLM failure circuit breaker (don't wait on a dead/quota-limited API for every job) ──────────
_fail_lock = threading.Lock()
_failures = 0
_disabled_until = 0.0


def _note_failure() -> None:
    global _failures, _disabled_until
    with _fail_lock:
        _failures += 1
        if _failures >= 3:
            _disabled_until = time.time() + 600


def _note_success() -> None:
    global _failures
    with _fail_lock:
        _failures = 0


def reset_circuit_breaker() -> None:
    global _failures, _disabled_until
    with _fail_lock:
        _failures, _disabled_until = 0, 0.0


# ─── normalising + scoring ────────────────────────────────────────────────────
def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def normalize_analysis(raw: dict, jd_text: str) -> dict:
    """Coerce the LLM's answer into known vocabularies and verify its closing-date quote."""
    reqs = []
    for r in raw.get("requirements") or []:
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        verdict = str(r.get("verdict", "")).strip().lower()
        importance = str(r.get("importance", "")).strip().lower()
        category = str(r.get("category", "")).strip().lower()
        reqs.append({
            "text": str(r["text"]).strip()[:90],
            "importance": importance if importance in IMPORTANCE_WEIGHT else "must",
            "category": category if category in ("skill", "experience", "education", "other") else "skill",
            "verdict": verdict if verdict in VERDICT_VALUE else "no",
            "evidence": str(r.get("evidence") or "").strip()[:200],
        })
    knockouts = [{"text": str(k.get("text", "")).strip()[:140], "blocks_candidate": bool(k.get("blocks_candidate"))}
                 for k in (raw.get("knockouts") or []) if isinstance(k, dict)]
    try:
        fit = max(0, min(100, int(raw.get("role_fit", 50))))
    except (TypeError, ValueError):
        fit = 50

    # Anti-hallucination: accept a deadline only if its quote really appears in the job text.
    closing, quote = "", _norm_text(raw.get("closing_date_quote"))
    if raw.get("closing_date") and quote and quote in _norm_text(jd_text):
        closing = str(raw["closing_date"]).strip()
    return {"requirements": reqs, "knockouts": knockouts, "role_fit": fit,
            "summary": str(raw.get("summary") or "").strip()[:300], "closing_date": closing}


def _weighted(reqs: List[dict]) -> float:
    total = sum(IMPORTANCE_WEIGHT[r["importance"]] for r in reqs)
    got = sum(IMPORTANCE_WEIGHT[r["importance"]] * VERDICT_VALUE[r["verdict"]] for r in reqs)
    return 100.0 * got / total if total else 0.0


def score_from_analysis(analysis: dict) -> FitResult:
    """
    Pure arithmetic over the verdicts. "must" requirements weigh 3x "nice"; partial counts half.
    A "must" education requirement answered "no" (wrong degree level / not enrolled) caps the overall at GATE_CAP.
    skills = skill/other requirements, experience = experience/education requirements (80 if the job
    names none, e.g. most internships), overall = 40% skills + 35% experience + 25% role fit, capped when
    the skills match is poor (same blend the old scorer used, so tracker columns stay comparable).
    """
    try:
        from services.ats_scorer import compute_overall_score
    except ImportError:
        from backend.services.ats_scorer import compute_overall_score

    reqs = analysis["requirements"]
    skill_reqs = [r for r in reqs if r["category"] in ("skill", "other")]
    exp_reqs = [r for r in reqs if r["category"] in ("experience", "education")]
    skills = round(_weighted(skill_reqs)) if skill_reqs else (round(_weighted(reqs)) if reqs else 60)
    experience = round(_weighted(exp_reqs)) if exp_reqs else 80
    fit = analysis["role_fit"]

    blockers = [k["text"] for k in analysis["knockouts"] if k["blocks_candidate"]]
    eligible = not blockers
    overall = compute_overall_score(skills, experience, fit) if eligible else 0
    gate = [r["text"] for r in reqs if r["importance"] == "must" and r["category"] == "education" and r["verdict"] == "no"]
    if gate and eligible:
        overall = min(overall, GATE_CAP)  # a missing degree/enrolment requirement can't be offset by strong skills

    matched = [r["text"] + (" (partial)" if r["verdict"] == "partial" else "") for r in reqs if r["verdict"] != "no"]
    missing = [r["text"] for r in reqs if r["verdict"] == "no" and r["importance"] == "must"]
    cd = None
    if analysis.get("closing_date"):
        try:
            from services.closing_date import parse_date, _plausible
        except ImportError:
            from backend.services.closing_date import parse_date, _plausible
        cd = _plausible(parse_date(analysis["closing_date"]))
    return FitResult(
        eligible=eligible, knockout_reason="; ".join(blockers) or None,
        skills_score=skills, experience_score=experience, role_fit=fit, overall=overall,
        matched=matched, missing=missing, summary=analysis["summary"], requirements=reqs, closing_date=cd,
    )


# ─── public API ───────────────────────────────────────────────────────────────
def analyze_fit(candidate: dict, title: str, company: str, jd_text: str, level: Optional[str] = None,
                llm: Optional[Callable[[str], str]] = None, use_cache: bool = True) -> FitResult:
    """Score `candidate` against one job. Raises FitUnavailable if no trustworthy analysis can be made."""
    jd_text = (jd_text or "").strip()
    if len(jd_text) < 100:
        raise FitUnavailable("job description too short to analyse")
    profile_text = candidate_profile_text(candidate)
    key = hashlib.sha256(f"{PROMPT_VERSION}|{level}|{title}|{company}|{profile_text}|{jd_text[:MAX_JD_CHARS]}".encode()).hexdigest()

    if use_cache:
        cached = _cache_get(key)
        if cached:
            res = score_from_analysis(cached)
            res.from_cache = True
            return res
    if time.time() < _disabled_until:
        raise FitUnavailable("LLM temporarily disabled after repeated failures")

    try:
        raw = (llm or _default_llm)(_build_prompt(profile_text, title, company, jd_text, level))
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip())
        analysis = normalize_analysis(json.loads(text), jd_text)
    except Exception as e:
        _note_failure()
        raise FitUnavailable(f"LLM analysis failed: {type(e).__name__}: {str(e)[:120]}") from e
    if len(analysis["requirements"]) < 2:
        _note_failure()
        raise FitUnavailable("LLM returned too few requirements")
    _note_success()
    if use_cache:
        _cache_put(key, analysis)
    return score_from_analysis(analysis)


def fit_summary_line(res: FitResult, max_gaps: int = 3) -> str:
    """One line for the tracker: why, plus the top gaps."""
    gaps = "; ".join(res.missing[:max_gaps])
    return (res.summary + (f" Gaps: {gaps}." if gaps else "")).strip()


async def score_job(job: dict, candidate: dict, level: Optional[str] = None, timeout: float = 90.0,
                    llm: Optional[Callable[[str], str]] = None) -> bool:
    """
    Score a job dict in place (same keys the keyword scorer sets, plus fit_summary / scoring / knockout /
    llm_closing_date). Returns True when the AI analysis succeeded; False leaves the job untouched.
    """
    try:
        res = await asyncio.wait_for(asyncio.to_thread(
            analyze_fit, candidate, job.get("title") or "", job.get("company") or "",
            job.get("description") or "", level, llm), timeout=timeout)
    except (FitUnavailable, asyncio.TimeoutError):
        return False
    except Exception:
        return False
    job.update({
        "ats_score": res.overall, "score": res.overall, "skills_score": res.skills_score,
        "exp_score": res.experience_score, "role_fit_score": res.role_fit,
        "matched_skills": res.matched, "missing_skills": res.missing,
        "fit_summary": fit_summary_line(res), "scoring": "AI", "estimated": False,
        "knockout": None if res.eligible else res.knockout_reason,
        "llm_closing_date": res.closing_date.isoformat() if res.closing_date else None,
    })
    return True
