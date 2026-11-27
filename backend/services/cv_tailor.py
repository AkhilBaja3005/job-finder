"""
cv_tailor.py - tailor the CV to one job without inventing anything.

The model never writes a free-form CV. It returns a PLAN over your own material:
  * which of your existing bullets to keep, and in what order        (by index)
  * how to order your skills                                          (names must be in your profile)
  * a retargeted summary                                              (validated)
  * a few optional rewordings of single bullets                       (validated)
  * the job's key terms, so we can measure keyword visibility before/after

Everything is then CHECKED IN CODE against your profile text. Anything that cannot be verified is thrown away
and the original wording is kept, so the result can only re-order, trim and re-phrase what is already true.
A change log (what moved, what was reworded, which keywords you are still missing) is produced for review.

Rules enforced:
  - every role, company, date and degree is copied from your profile untouched (no role is ever dropped; each keeps >= 1 bullet)
  - a reworded bullet / the summary may only contain numbers that appear in your profile text, and only
    technology-like names (LangGraph, PyTorch, GPT-4, C++, AWS...) that appear in your profile text
  - a skill is shown only if your profile mentions it
"""

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import fit_scorer
from .resume_audit import _mentions

PROMPT_VERSION = "t1"
MAX_BULLETS_TOTAL = 14
MAX_SKILLS = 24
MAX_PROJECTS = 4
MAX_JD_CHARS = 6000
_PLACEHOLDER_LINKS = ("janedoe", "example.com", "yourname", "your-name", "username")


class TailorUnavailable(RuntimeError):
    """The model could not produce a usable plan; the master CV is used unchanged."""


@dataclass
class TailoredCV:
    cv: Dict[str, Any]
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    keywords: List[Dict[str, Any]] = field(default_factory=list)   # {term, evidenced, before, after}
    tailored: bool = True


# ─── master CV from the profile ───────────────────────────────────────────────
def _split_timeline(text: str):
    parts = re.split(r"\s*[–—-]\s*|\s+to\s+", str(text or "").strip(), maxsplit=1)
    return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "Present")


def master_cv_from_profile(candidate: dict) -> Dict[str, Any]:
    """The un-tailored CV: exactly the profile's content in CV shape (this is what tailoring starts from)."""
    links = [str(candidate[k]) for k in ("linkedin", "github", "portfolio")
             if candidate.get(k) and not any(p in str(candidate[k]).lower() for p in _PLACEHOLDER_LINKS)]
    phone = str(candidate.get("phone") or "")
    skills: List[str] = []
    for key in ("core_skills", "skills"):
        v = candidate.get(key)
        if isinstance(v, list):
            skills += [str(s) for s in v]
        elif isinstance(v, dict):
            for k, vals in v.items():
                skills += [str(x) for x in vals] if isinstance(vals, list) else []
    for vals in (candidate.get("skill_categories") or {}).values():
        skills += [str(x) for x in vals]

    experience = []
    for e in candidate.get("work_experience") or candidate.get("experience") or []:
        if not isinstance(e, dict):
            continue
        start, end = (e.get("start_date"), e.get("end_date") or "Present") if e.get("start_date") else _split_timeline(e.get("timeline"))
        experience.append({"company": e.get("company", ""), "role": e.get("role") or e.get("title", ""),
                           "start_date": start, "end_date": end,
                           "technologies": ", ".join(map(str, e.get("technologies") or [])),
                           "description": [str(b) for b in fit_scorer._bullets(e)]})
    education = []
    for e in candidate.get("education") or []:
        if isinstance(e, dict):
            start, end = _split_timeline(e.get("timeline")) if e.get("timeline") else (e.get("start_date", ""), e.get("graduation_date", ""))
            education.append({"institution": e.get("institution", ""), "degree": e.get("degree", ""), "field_of_study": "",
                              "start_date": start, "graduation_date": end})
    projects = []
    for p in candidate.get("projects") or []:
        if isinstance(p, dict):
            desc = p.get("description")
            projects.append({"title": p.get("title", ""), "technologies": [str(t) for t in p.get("technologies") or []],
                             "description": [str(d) for d in desc] if isinstance(desc, list) else ([str(desc)] if desc else [])})
    return {
        "name": candidate.get("name", ""), "email": candidate.get("email", ""),
        "phone": "" if phone.strip().lower() in ("", "not provided") else phone, "links": links,
        "summary": candidate.get("experience_summary") or candidate.get("summary") or "",
        "experience": experience, "education": education, "projects": projects,
        "skills": list(dict.fromkeys(skills)),
    }


def cv_text(cv: Dict[str, Any]) -> str:
    """Everything an ATS parser would read from the CV."""
    parts = [cv.get("summary", ""), " ".join(cv.get("skills") or [])]
    for e in cv.get("experience", []):
        parts += [e.get("company", ""), e.get("role", ""), e.get("technologies", "")] + list(e.get("description", []))
    for p in cv.get("projects", []):
        parts += [p.get("title", ""), " ".join(p.get("technologies", []))] + list(p.get("description", []))
    for e in cv.get("education", []):
        parts += [e.get("institution", ""), e.get("degree", "")]
    return "\n".join(str(x) for x in parts if x)


# ─── verification helpers ─────────────────────────────────────────────────────
_NUM = re.compile(r"\d[\d,.]*%?")
_TECH = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+[A-Z][A-Za-z0-9]+|[A-Za-z]+[0-9][A-Za-z0-9.\-]*|[A-Za-z0-9]+(?:\+\+|#))")


def _numbers(text: str) -> set:
    return {n.strip(".,") for n in _NUM.findall(text or "") if len(n.strip(".,")) >= 1}


def _has_word(text_lower: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token.lower())}(?![a-z0-9])", text_lower) is not None


def _unsupported(new_text: str, allowed_text: str) -> List[str]:
    """Numbers / technology-like names in `new_text` that do not appear in `allowed_text`."""
    low = allowed_text.lower()
    bad = [n for n in sorted(_numbers(new_text)) if n not in _numbers(allowed_text)]
    for tok in _TECH.findall(new_text):
        if not _has_word(low, tok):
            bad.append(tok)
    return list(dict.fromkeys(bad))


_FLUFF = ("highly motivated", "passionate", "proven ability", "proven track record", "results-driven", "results driven",
          "fast-paced", "dynamic", "leveraging", "synergy", "self-starter", "team player", "hard-working", "hardworking",
          "detail-oriented", "go-getter", "think outside", "driving adoption", "cross-disciplinary", "cross-functional",
          "high-impact", "world-class", "cutting-edge")
# neutral long words a faithful rewording may use even if the profile never spells them out
_NEUTRAL = {"across", "through", "within", "between", "toward", "towards", "around", "during", "building", "builds", "designed",
            "designing", "developed", "developing", "engineer", "engineering", "experience", "experienced", "systems", "production",
            "applied", "focused", "strong", "background", "ability", "projects", "product", "research", "software", "solutions",
            "machine", "learning", "models", "analysis", "delivered", "delivering", "scalable", "enterprise", "improved", "improving"}


def _stem(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())[:5]


def _vocab(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z\-']+", text or "")}


def _off_vocabulary(new_text: str, allowed_text: str) -> List[str]:
    """Longer words in `new_text` that the profile never uses (a sign the model added wording of its own)."""
    allowed = _vocab(allowed_text)
    bad = []
    for w in re.findall(r"[A-Za-z][A-Za-z\-']{5,}", new_text or ""):
        if w.lower() in _NEUTRAL or _stem(w) in allowed:
            continue
        bad.append(w)
    return list(dict.fromkeys(bad))


def _problems_with_prose(new_text: str, allowed_text: str, unevidenced_keywords: List[str], original: Optional[str] = None) -> List[str]:
    """Everything wrong with a model-written summary / rewording. Empty list = acceptable."""
    probs: List[str] = []
    low = new_text.lower()
    probs += [f"filler '{f}'" for f in _FLUFF if f in low]
    off = _off_vocabulary(new_text, allowed_text)
    if off:
        probs.append("wording not in your profile: " + ", ".join(off[:6]))
    probs += [f"mentions '{k}' which your profile does not evidence" for k in unevidenced_keywords if _mentions(low, k)]
    probs += [f"adds {x}" for x in _unsupported(new_text, allowed_text)]
    if original is not None:
        lost = [n for n in sorted(_numbers(original)) if n not in _numbers(new_text)]
        if lost:
            probs.append("drops the numbers " + ", ".join(lost))
    return probs


# ─── the plan ─────────────────────────────────────────────────────────────────
def _schema():
    from pydantic import BaseModel

    class ExpPlan(BaseModel):
        exp_index: int
        keep: List[int]

    class Rewrite(BaseModel):
        exp_index: int
        bullet_index: int
        new_text: str

    class TailorPlan(BaseModel):
        summary: str
        experience: List[ExpPlan]
        rewrites: List[Rewrite]
        project_order: List[int]
        skills: List[str]
        keywords: List[str]

    return TailorPlan


def _default_llm(prompt: str) -> str:
    return fit_scorer._default_llm(prompt, _schema())


def _numbered(cv: Dict[str, Any]) -> str:
    out = []
    for i, e in enumerate(cv["experience"]):
        out.append(f"[exp {i}] {e['role']} at {e['company']} ({e['start_date']} - {e['end_date']})")
        out += [f"    ({j}) {b}" for j, b in enumerate(e["description"])]
    out.append("PROJECTS:")
    for i, p in enumerate(cv["projects"]):
        out.append(f"[proj {i}] {p['title']}: " + " ".join(p["description"]))
    out.append("SKILLS: " + ", ".join(cv["skills"]))
    return "\n".join(out)


def _build_prompt(master: Dict[str, Any], jd_text: str, title: str, company: str, level: Optional[str], feedback: str = "") -> str:
    seeking = f"The candidate is applying for a {level}-level role. " if level and level != "any" else ""
    return f"""You tailor a CV to ONE job by choosing and ordering the candidate's EXISTING material. {seeking}
You may NOT add experience, skills, tools, employers, numbers or claims that are not already in the CV below.

Return JSON:
- summary: a 2-3 sentence professional summary (max 55 words) aimed at this job, built ONLY from facts in the CV.
  Reuse the CV's own words. No first person, no numbers or tool names that are not in the CV, and NO filler such as
  "highly motivated", "passionate", "proven", "dynamic", "leveraging", "fast-paced". Do not call the candidate a "student"
  unless the CV says so. Do not mention job keywords the candidate has no evidence for.
- experience: for EVERY role (exp_index 0..N) the list `keep` of bullet indices to show, most relevant to the job first.
  Keep up to 3–4 strong bullets per role so the 1-page resume stays rich and balanced; only drop bullets that are clearly off-topic.
- rewrites: optional, at most 3. Re-phrase ONE existing bullet (exp_index, bullet_index) only to put the job's relevant
  terms first, and only when it stays exactly as true and specific. KEEP every number and tool name of the original, add
  no new claim or soft-skill wording, and use only words already in the CV. When in doubt, do not rewrite.
- project_order: indices of the projects most relevant to this job, best first (max {MAX_PROJECTS}); omit irrelevant ones.
- skills: the CV's skills reordered so the ones this job asks for come first. Use only skills from the SKILLS list.
- keywords: the 10-15 most important skills/tools/terms THIS JOB asks for (whether or not the candidate has them).

JOB: {title} at {company}
JOB DESCRIPTION:
{jd_text[:MAX_JD_CHARS]}

CANDIDATE CV (numbers in brackets are the indices to use):
{_numbered(master)}
{feedback}"""


def _call_plan(master, jd_text, title, company, level, llm, feedback=""):
    try:
        raw = (llm or _default_llm)(_build_prompt(master, jd_text, title, company, level, feedback))
        plan = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip()))
        if not isinstance(plan, dict):
            raise ValueError("plan is not a JSON object")
        return plan
    except Exception as e:
        raise TailorUnavailable(f"tailoring failed: {type(e).__name__}: {str(e)[:120]}") from e


def tailor_cv(master: Dict[str, Any], jd_text: str, title: str = "", company: str = "", level: Optional[str] = None,
              llm: Optional[Callable[[str], str]] = None) -> TailoredCV:
    """
    Return the CV tailored to the job, or raise TailorUnavailable. Every claim is verified in code. If the model's first
    plan has parts that fail verification, it is asked ONCE to fix them (told exactly what was wrong); whatever still fails
    is dropped and your original wording is kept.
    """
    if len((jd_text or "").strip()) < 100:
        raise TailorUnavailable("job description too short to tailor to")
    plan = _call_plan(master, jd_text, title, company, level, llm)
    result, problems = _apply_plan(master, plan)
    if problems:
        feedback = ("\nYOUR PREVIOUS PLAN HAD THESE PROBLEMS; fix them (or omit that part):\n" + "\n".join(f"- {p}" for p in problems))
        try:
            plan2 = _call_plan(master, jd_text, title, company, level, llm, feedback)
            result2, problems2 = _apply_plan(master, plan2)
            if len(problems2) < len(problems):
                result, problems = result2, problems2
        except TailorUnavailable:
            pass
    return result


def _apply_plan(master: Dict[str, Any], plan: Dict[str, Any]):
    """Verify `plan` against the profile and build the tailored CV. Returns (TailoredCV, list of problems found)."""
    base_text = cv_text(master)
    cv = copy.deepcopy(master)
    changes: List[str] = []
    warnings: List[str] = []

    # ── summary ──
    problems: List[str] = []                      # fed back to the model once, so it can fix them
    unevidenced = [t for t in (str(k).strip() for k in plan.get("keywords") or []) if t and not _mentions(base_text.lower(), t)]
    new_sum = str(plan.get("summary") or "").strip()
    words = len(new_sum.split())
    sum_probs = _problems_with_prose(new_sum, base_text, unevidenced) if new_sum else []
    headline = _numbers(master["summary"])
    if new_sum and headline and not (headline & _numbers(new_sum)):
        sum_probs.append("drops the proof point in your original summary (" + ", ".join(sorted(headline)) + ")")   # keep the strongest evidence
    if not new_sum or words < 12 or words > 70:
        warnings.append(f"Model summary rejected (length {words} words); kept your original summary.")
        problems.append(f"summary has {words} words; it must be 12-70")
    elif sum_probs:
        warnings.append(f"Model summary rejected ({'; '.join(sum_probs[:4])}); kept your original summary.")
        problems.append("summary: " + "; ".join(sum_probs[:4]))
    elif new_sum != master["summary"]:
        cv["summary"] = new_sum
        changes.append(f"SUMMARY rewritten for this job.\n    before: {master['summary']}\n    after:  {new_sum}")

    # ── bullets: select + order by index, then verified rewrites ──
    total_cap = MAX_BULLETS_TOTAL
    plans = {p.get("exp_index"): p.get("keep") for p in plan.get("experience") or [] if isinstance(p, dict)}
    rewrites = {}
    for r in plan.get("rewrites") or []:
        if isinstance(r, dict) and isinstance(r.get("exp_index"), int) and isinstance(r.get("bullet_index"), int):
            rewrites[(r["exp_index"], r["bullet_index"])] = str(r.get("new_text") or "").strip()
    used = 0
    for i, exp in enumerate(cv["experience"]):
        orig = master["experience"][i]["description"]
        keep = [j for j in (plans.get(i) or []) if isinstance(j, int) and 0 <= j < len(orig)]
        keep = list(dict.fromkeys(keep)) or list(range(min(len(orig), 3)))      # never leave a role empty
        if not orig:
            continue
        remaining_roles = len(cv["experience"]) - i - 1
        room = max(1, total_cap - used - remaining_roles)
        keep = keep[:room]
        new_bullets = []
        for j in keep:
            text = orig[j]
            rw = rewrites.get((i, j))
            if rw and rw != text:
                # may only use the profile's own wording, keep every number of the original, add no unsupported keyword
                rw_probs = _problems_with_prose(rw, text + "\n" + base_text, unevidenced, original=text)
                if len(rw.split()) > int(len(text.split()) * 1.3) + 12:
                    rw_probs.append("too long")
                if rw_probs:
                    warnings.append(f"Reworded bullet rejected ({exp['company']}): {'; '.join(rw_probs[:3])}; kept the original.")
                    problems.append(f"rewrite of bullet {j} in role {i}: " + "; ".join(rw_probs[:3]))
                else:
                    changes.append(f"REWORDED ({exp['role']} at {exp['company']}).\n    before: {text}\n    after:  {rw}")
                    text = rw
            new_bullets.append(text)
        used += len(new_bullets)
        exp["description"] = new_bullets
        dropped = len(orig) - len(keep)
        reordered = keep != sorted(keep)
        if dropped or reordered:
            changes.append(f"BULLETS {exp['role']} at {exp['company']}: showing {len(keep)} of {len(orig)}"
                           + (", reordered by relevance" if reordered else "")
                           + (f"; left out: " + " | ".join(orig[j][:70] + "…" for j in range(len(orig)) if j not in keep) if dropped else ""))

    # ── projects ──
    order = [j for j in plan.get("project_order") or [] if isinstance(j, int) and 0 <= j < len(master["projects"])]
    order = list(dict.fromkeys(order))[:MAX_PROJECTS] or list(range(min(len(master["projects"]), MAX_PROJECTS)))
    cv["projects"] = [master["projects"][j] for j in order]
    if order != list(range(len(master["projects"]))):
        left = [p["title"] for k, p in enumerate(master["projects"]) if k not in order]
        changes.append("PROJECTS reordered by relevance" + (f"; left out: {', '.join(left)}" if left else "") + ".")

    # ── skills: reorder what you have; show only skills your profile mentions ──
    profile_low = base_text.lower()
    have = {s.lower(): s for s in master["skills"]}
    ordered: List[str] = []
    for s in plan.get("skills") or []:
        s = str(s).strip()
        canon = have.get(s.lower())
        if canon is None and s and _mentions(profile_low, s):
            canon = s                                                    # evidenced elsewhere in the profile
        elif canon is None and s:
            warnings.append(f"Skill '{s}' suggested by the model is not in your profile; not added.")
        if canon and canon not in ordered:
            ordered.append(canon)
    for s in master["skills"]:
        if s not in ordered:
            ordered.append(s)
    cv["skills"] = ordered[:MAX_SKILLS]
    if cv["skills"][: len(master["skills"])] != master["skills"][: len(cv["skills"])]:
        changes.append("SKILLS reordered so the job's key skills come first: " + ", ".join(cv["skills"][:8]) + ", …")

    # ── keyword visibility before / after (evidence is decided by code, not the model) ──
    before_text, after_text = base_text.lower(), cv_text(cv).lower()
    kws = []
    for term in dict.fromkeys(str(k).strip() for k in plan.get("keywords") or [] if str(k).strip()):
        kws.append({"term": term, "evidenced": _mentions(profile_low, term),
                    "before": _mentions(before_text, term), "after": _mentions(after_text, term)})
    return TailoredCV(cv=cv, changes=changes, warnings=warnings, keywords=kws[:20], tailored=True), problems


def keyword_summary(result: TailoredCV) -> Dict[str, Any]:
    ev = [k for k in result.keywords if k["evidenced"]]
    return {"evidenced": len(ev), "before": sum(1 for k in ev if k["before"]), "after": sum(1 for k in ev if k["after"]),
            "gaps": [k["term"] for k in result.keywords if not k["evidenced"]]}


def render_changes_md(result: TailoredCV, title: str, company: str) -> str:
    ks = keyword_summary(result)
    lines = [f"# CV changes for {title} at {company}", "",
             "Nothing here was invented: every line comes from your profile (`candidate_profile.json`). "
             "Review each change; edit `cv.json` and run `./jf prepare --render-only --ids <ID>` to rebuild the PDF.", ""]
    if ks["evidenced"]:
        lines += [f"**Job keywords your profile supports: {ks['evidenced']}**.  Visible on the CV: "
                  f"{ks['before']} before, **{ks['after']} after** tailoring.", ""]
    if ks["gaps"]:
        lines += ["**Job keywords you do NOT have evidence for** (not added, do not claim these): " + ", ".join(ks["gaps"]), ""]
    if result.keywords:
        lines += ["| Job keyword | In your profile | On master CV | On this CV |", "|---|---|---|---|"]
        lines += [f"| {k['term']} | {'yes' if k['evidenced'] else 'no'} | {'yes' if k['before'] else 'no'} | {'yes' if k['after'] else 'no'} |"
                  for k in result.keywords]
        lines.append("")
    lines += ["## What changed", ""] + ([f"- {c}" for c in result.changes] or ["- Nothing needed changing."]) + [""]
    if result.warnings:
        lines += ["## Rejected suggestions (kept your original wording)", ""] + [f"- {w}" for w in result.warnings] + [""]
    return "\n".join(lines)
