"""
resume_audit.py - AI "master resume health" audit (replaces the fixed-taxonomy skill count).

Questions answered
- For the roles you are targeting, which skills do postings typically ask for, and does your resume
  show them? Each is classified: listed (in the Skills section, where ATS parsers look), evidenced
  (shown in projects/experience but NOT listed - an easy win), or absent (a real gap).
- Which other skills does your profile evidence that you never listed?
- Are bullets quantified, is the summary the right length, how long is the timeline? (plain arithmetic)

The LLM only proposes; code verifies. A "listed" claim must really appear in the skills section and an
"evidenced" claim must really appear somewhere in the profile, otherwise it is downgraded, so the model
cannot invent strengths. Falls back to the old keyword audit if the LLM is unavailable.
"""

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional

# Relative imports on purpose: this package is importable as both `services.*` and `backend.services.*`,
# and importing fit_scorer under the other name would create a second, different FitUnavailable class.
from . import fit_scorer

PROMPT_VERSION = "a2"
_QUANT = re.compile(r"\b\d+(?:\.\d+)?%|\b\$\d+|\b£\d+|\bINR\s*\d+|\b\d+\+|\b\d+x\b|\b\d[\d,]*\s*(?:ms|s|days|weeks|months|users|teams|agents|requests)\b", re.I)
_SKILLS_LINE_TIP = re.compile(r"\bskills?\b.{0,40}\b(line|section|list)\b|\b(line|section|list)\b.{0,40}\bskills?\b", re.I)
_WEAK_SUMMARY = re.compile(r"strong foundation in|passionate about|seeking an entry|hard[- ]working|team player", re.I)


# ─── deterministic parts ──────────────────────────────────────────────────────
def skills_section_text(candidate: dict) -> str:
    """Everything a parser would read as the Skills section."""
    parts: List[str] = []
    for key in ("core_skills", "skills"):
        v = candidate.get(key)
        if isinstance(v, list):
            parts += [str(x) for x in v]
        elif isinstance(v, dict):
            for k, vals in v.items():
                parts += [str(k)] + ([str(x) for x in vals] if isinstance(vals, list) else [])
    for vals in (candidate.get("skill_categories") or {}).values():
        parts += [str(x) for x in vals]
    return " ".join(parts)


def bullet_stats(candidate: dict) -> Dict[str, int]:
    bullets: List[str] = []
    for exp in candidate.get("work_experience") or candidate.get("experience") or []:
        if isinstance(exp, dict):
            bullets += [b for b in fit_scorer._bullets(exp) if isinstance(b, str)]
    for proj in candidate.get("projects") or []:
        if isinstance(proj, dict) and proj.get("description"):
            bullets.append(str(proj["description"]))
    quantified = sum(1 for b in bullets if _QUANT.search(b))
    return {"total": len(bullets), "quantified": quantified,
            "pct": round(100 * quantified / len(bullets)) if bullets else 0}


def _variants(skill: str) -> List[str]:
    """'Retrieval-Augmented Generation (RAG)' -> the full name, 'RAG', ... so any common spelling counts."""
    out = [skill]
    out += re.findall(r"\(([^)]+)\)", skill)
    base = re.sub(r"\([^)]*\)", " ", skill)
    out += [p.strip() for p in re.split(r"/| or ", base) if p.strip()]
    return list(dict.fromkeys(v for v in out if v.strip()))


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(t) > 1 and t not in ("and", "of", "the", "for", "with")]


def _has_token(text_lower: str, tok: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", text_lower) is not None


def _mentions(text_lower: str, skill: str) -> bool:
    """True if all meaningful words of `skill` (or of one of its spellings, e.g. an acronym in brackets) appear as whole words."""
    for v in _variants(skill):
        toks = _tokens(v)
        if toks and all(_has_token(text_lower, t) for t in toks):
            return True
    return False


def _evidence_supported(evidence: str, text_lower: str) -> bool:
    """The model's cited evidence must really be in the profile (most of its content words appear there)."""
    toks = [t for t in _tokens(evidence) if len(t) > 3]
    return len(toks) >= 2 and sum(_has_token(text_lower, t) for t in toks) / len(toks) >= 0.7


def _snippet(profile_text: str, skill: str, width: int = 70) -> str:
    for v in _variants(skill):
        m = re.search(rf"(?<![A-Za-z0-9]){re.escape(v)}(?![A-Za-z0-9])", profile_text, re.I)
        if m:
            lo = max(0, m.start() - width // 2)
            return re.sub(r"\s+", " ", profile_text[lo: m.end() + width // 2]).strip(" *-")
    return ""


# ─── LLM part ─────────────────────────────────────────────────────────────────
def _schema():
    from pydantic import BaseModel

    class ExpectedSkill(BaseModel):
        skill: str
        status: str
        evidence: str

    class Audit(BaseModel):
        target_field: str
        expected_skills: List[ExpectedSkill]
        other_evidenced_skills: List[str]
        suggestions: List[str]

    return Audit


def _default_llm(prompt: str) -> str:
    return fit_scorer._default_llm(prompt, _schema())


def _build_prompt(profile_text: str, targets: str) -> str:
    return f"""You are auditing a candidate's master resume for ATS parsing and recruiter screening.
TARGET ROLES: {targets}

Return JSON with:
- target_field: the field these roles are in (2-5 words)
- expected_skills: 10-15 skills/tools/methods that job postings for the TARGET ROLES commonly require, most important
  first. For each:
    skill: short name
    status: "listed" if it appears in the candidate's SKILLS line;
            "evidenced" if it is NOT in the SKILLS line but the profile shows real use of it (projects, work);
            "absent" if the profile shows no use of it
    evidence: for "evidenced", the profile fact showing it (short); else ""
- other_evidenced_skills: up to 10 tools/skills/methods the profile clearly shows (in projects, work, education) that are
  NOT in the SKILLS line and not already in expected_skills
- suggestions: 2-4 concrete improvements (add specific skills to the Skills line, reword a vague bullet, add a missing
  link, ...). Do NOT suggest adding skills to the Skills line (that is handled separately). Use ONLY facts in the
  profile and never invent numbers or metrics.

CANDIDATE PROFILE:
{profile_text}
"""


def _verify(raw: dict, candidate: dict, profile_text: str) -> Dict[str, Any]:
    """Downgrade/clean the LLM's claims against the real profile text."""
    skills_l = skills_section_text(candidate).lower()
    prof_l = profile_text.lower()
    expected: List[Dict[str, str]] = []
    for e in raw.get("expected_skills") or []:
        if not isinstance(e, dict) or not str(e.get("skill", "")).strip():
            continue
        name = str(e["skill"]).strip()[:60]
        claimed_evidence = str(e.get("evidence") or "").strip()
        if _mentions(skills_l, name):
            status, evidence = "listed", ""                       # it really is in the Skills section
        elif _mentions(prof_l, name):
            status = "evidenced"                                  # used in the profile, whatever the model said
            evidence = claimed_evidence if _evidence_supported(claimed_evidence, prof_l) else _snippet(profile_text, name)
        elif str(e.get("status", "")).strip().lower() == "evidenced" and _evidence_supported(claimed_evidence, prof_l):
            status, evidence = "evidenced", claimed_evidence      # e.g. 'LLMs' vs 'large language models'
        else:
            status, evidence = "absent", ""                       # nothing in the profile supports it
        expected.append({"skill": name, "status": status, "evidence": evidence[:140]})
    expected = list({e["skill"].lower(): e for e in expected}.values())

    listed_names = {e["skill"].lower() for e in expected}
    other = []
    for s in raw.get("other_evidenced_skills") or []:
        s = str(s).strip()[:60]
        if s and s.lower() not in listed_names and not _mentions(skills_l, s) and _mentions(prof_l, s):
            other.append(s)
    return {
        "target_field": str(raw.get("target_field") or "").strip()[:60],
        "expected_skills": expected,
        "other_evidenced_skills": list(dict.fromkeys(other))[:10],
        # "add X to the Skills line" tips are generated (and verified) by code below; drop the model's duplicates
        "suggestions": [str(x).strip()[:260] for x in (raw.get("suggestions") or [])
                        if str(x).strip() and not _SKILLS_LINE_TIP.search(str(x))][:4],
    }


def audit_master_resume(candidate: dict, prefs: Optional[dict] = None,
                        llm: Optional[Callable[[str], str]] = None, use_cache: bool = True) -> Dict[str, Any]:
    """
    Returns a dict with the same keys the old audit had (ats_score, skills_count, total_bullets, quantified_bullets,
    quantified_percentage, candidate_years, suggestions) plus engine, target_field, skills_listed, hidden_skills, gaps.
    Raises fit_scorer.FitUnavailable if the AI analysis cannot be produced.
    """
    prefs = prefs or {}
    topics = [t for t in prefs.get("topics", []) if t]
    level = prefs.get("level")
    targets = (", ".join(f"{t} {level or ''}".strip() for t in topics)
               or ", ".join(prefs.get("target_roles", [])) or "the roles suggested by the candidate's own background")
    profile_text = fit_scorer.candidate_profile_text(candidate)
    key = "audit|" + hashlib.sha256(f"{PROMPT_VERSION}|{targets}|{profile_text}".encode()).hexdigest()

    # Cache the model's RAW answer and verify on every read, so improving the checks never serves stale verdicts.
    raw_obj = fit_scorer._cache_get(key) if use_cache else None
    if raw_obj is None:
        try:
            raw = (llm or _default_llm)(_build_prompt(profile_text, targets))
            raw_obj = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip()))
            if not isinstance(raw_obj, dict):
                raise ValueError("answer is not a JSON object")
        except Exception as e:
            raise fit_scorer.FitUnavailable(f"audit failed: {type(e).__name__}: {str(e)[:120]}") from e
        verified = _verify(raw_obj, candidate, profile_text)
        if len(verified["expected_skills"]) < 3:
            raise fit_scorer.FitUnavailable("audit returned too few skills")
        if use_cache:
            fit_scorer._cache_put(key, raw_obj)
    else:
        verified = _verify(raw_obj, candidate, profile_text)

    expected = verified["expected_skills"]
    value = {"listed": 1.0, "evidenced": 0.6, "absent": 0.0}   # evidenced-but-unlisted still hides from ATS skill filters
    coverage = round(100 * sum(value[e["status"]] for e in expected) / len(expected))

    from .ats_scorer import calculate_flattened_experience
    years = calculate_flattened_experience({"work_experience": candidate.get("work_experience") or candidate.get("experience") or []})[0]
    stats = bullet_stats(candidate)
    quant_score = min(100, round(stats["pct"] * 1.2))
    exp_score = 90 if years >= 2 else 70
    score = max(40, min(98, round(0.40 * coverage + 0.35 * exp_score + 0.25 * quant_score)))

    tips: List[str] = []
    hidden = [e for e in expected if e["status"] == "evidenced"]
    if hidden:
        tips.append("Add to your Skills section (already shown in your experience/projects): "
                    + ", ".join(e["skill"] for e in hidden) + ".")
    if verified["other_evidenced_skills"]:
        tips.append("Also evidenced but unlisted: " + ", ".join(verified["other_evidenced_skills"]) + ".")
    if stats["total"] and stats["pct"] < 50:
        tips.append(f"Quantify more achievements: only {stats['pct']}% of bullets carry a measurable result (aim for 60%+).")
    summary = candidate.get("experience_summary") or candidate.get("summary") or ""
    words = len(summary.split())
    if not summary:
        tips.append("Add a professional summary (25-50 words) naming your target field and strongest proof.")
    elif words < 15 or words > 70:
        tips.append(f"Summary is {words} words; 25-50 reads best to a recruiter scanning.")
    if _WEAK_SUMMARY.search(summary):
        tips.append("Replace generic summary phrases with concrete proof from your experience.")
    tips += verified["suggestions"]

    return {
        "engine": "ai", "ats_score": score, "target_field": verified["target_field"], "targets": targets,
        "skills_coverage": coverage,
        "skills_count": sum(1 for e in expected if e["status"] == "listed"),
        "skills_listed": [e["skill"] for e in expected if e["status"] == "listed"],
        "hidden_skills": [{"skill": e["skill"], "evidence": e["evidence"]} for e in hidden],
        "other_evidenced_skills": verified["other_evidenced_skills"],
        "gaps": [e["skill"] for e in expected if e["status"] == "absent"],
        "expected_total": len(expected),
        "total_bullets": stats["total"], "quantified_bullets": stats["quantified"], "quantified_percentage": stats["pct"],
        "candidate_years": round(years, 1), "suggestions": list(dict.fromkeys(tips))[:6],
    }


def skills_to_add(audit: Dict[str, Any], candidate: dict) -> List[str]:
    """Skills the profile evidences but doesn't list: safe to add to core_skills (never the 'absent' gaps)."""
    have = skills_section_text(candidate).lower()
    # target-relevant skills first; other evidenced items only if they are short, skill-like names
    out = [h["skill"] for h in audit.get("hidden_skills", [])] + [o for o in audit.get("other_evidenced_skills", []) if len(o) <= 25]
    return [s for s in dict.fromkeys(out) if s.lower() not in have]
