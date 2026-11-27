"""`job-finder ats --jd-file/--jd-url`: score a resume against one job description with a full breakdown."""

import sys
from typing import Any, Dict, Optional

from job_finder import ui


def score_against_jd(candidate: Dict[str, Any], jd_text: str, keyword: bool = False,
                     title: str = "", company: str = "") -> Dict[str, Any]:
    """
    Score `candidate` against one job description. Uses the evidence-based AI analysis; falls back to the
    keyword engine (clearly labelled) if the LLM is unavailable or `keyword=True`.
    """
    if not keyword:
        try:
            try:
                from backend.services.fit_scorer import analyze_fit, FitUnavailable
            except ImportError:  # pragma: no cover
                from services.fit_scorer import analyze_fit, FitUnavailable
            try:
                res = analyze_fit(candidate, title, company, jd_text)
            except FitUnavailable as e:
                reason = str(e)
            else:
                if not res.eligible:
                    return {"engine": "ai", "eligible": False, "reason": res.knockout_reason, "overall": 0,
                            "summary": res.summary, "requirements": res.requirements}
                return {
                    "engine": "ai", "eligible": True, "overall": res.overall, "skills": res.skills_score,
                    "experience": res.experience_score, "role_fit": res.role_fit, "summary": res.summary,
                    "matched_skills": res.matched, "missing_skills": res.missing, "requirements": res.requirements,
                    "closing_date": res.closing_date.isoformat() if res.closing_date else None,
                }
        except Exception as e:  # pragma: no cover - never lose the keyword fallback
            reason = f"{type(e).__name__}: {e}"
        fallback_note = f"AI analysis unavailable ({reason}); showing the keyword engine instead."
    else:
        fallback_note = None
    out = _keyword_score(candidate, jd_text)
    out["engine"] = "keyword"
    if fallback_note:
        out["note"] = fallback_note
    return out


def _keyword_score(candidate: Dict[str, Any], jd_text: str) -> Dict[str, Any]:
    """The old deterministic keyword scorer (fixed skill taxonomy)."""
    try:
        from backend.services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
    except ImportError:  # pragma: no cover - alternate import root
        from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score

    result = compute_ats_score(candidate, jd_text)
    if not result.eligible:
        return {"eligible": False, "reason": result.knockout_reason, "overall": 0}
    role_fit = estimate_role_fit_score(candidate, jd_text)
    overall = compute_overall_score(result.skills_score, result.experience_score, role_fit)
    return {
        "eligible": True,
        "overall": overall,
        "skills": result.skills_score,
        "experience": result.experience_score,
        "role_fit": role_fit,
        "candidate_years": result.candidate_years,
        "required_years": result.required_years,
        "matched_skills": result.matched_skills,
        "missing_skills": result.missing_skills,
        "breakdown": {k: v for k, v in result.score_breakdown.items() if k != "skill_weights"},
        "skill_weights": result.score_breakdown.get("skill_weights", {}),
    }


def load_jd_text(jd_file: Optional[str] = None, jd_url: Optional[str] = None) -> str:
    if jd_file:
        if jd_file == "-":
            return sys.stdin.read()
        with open(jd_file, encoding="utf-8") as fh:
            return fh.read()
    if jd_url:
        import asyncio
        try:
            from backend.services.scraper import scrape_job_description
        except ImportError:  # pragma: no cover
            from services.scraper import scrape_job_description
        scraped = asyncio.run(scrape_job_description(jd_url))
        return scraped.get("description", "") if isinstance(scraped, dict) else ""
    return ""


def render(result: Dict[str, Any], as_json: bool = False) -> int:
    if as_json:
        ui.print_json(result)
        return 0 if result.get("eligible") else 1
    if not result.get("eligible"):
        ui.error(f"Not eligible for this role: {result.get('reason')}")
        if result.get("requirements"):
            ui.info(result.get("summary") or "")
        return 1
    if result.get("engine") == "ai":
        ui.key_values("Fit for this job (AI analysis, evidence-based)", {
            "Overall": f"{result['overall']}/100", "Skills": result["skills"],
            "Experience / education": result["experience"], "Role fit": result["role_fit"],
            "Closing date": result.get("closing_date") or "not stated",
            "Verdict": result.get("summary") or "-",
        })
        sym = {"yes": "met", "partial": "partial", "no": "NOT met"}
        ui.print_table("Requirements", ["Requirement", "Need", "Your profile", "Evidence"],
                       [[r["text"][:44], r["importance"], sym.get(r["verdict"], r["verdict"]), (r["evidence"] or "-")[:60]]
                        for r in result["requirements"]], status_col=None)
        return 0
    if result.get("note"):
        ui.warn(result["note"])
    ui.key_values("ATS score for this job (keyword engine)", {
        "Overall": f"{result['overall']}/100",
        "Skills": result["skills"],
        "Experience": f"{result['experience']} ({result['candidate_years']}y vs {result['required_years']}y required)",
        "Role fit": result["role_fit"],
    })
    weights = result.get("skill_weights", {})
    rows = []
    for skill in result["matched_skills"]:
        rows.append([skill, "matched", f"{weights.get(skill, 0):.0%}" if skill in weights else "-"])
    for skill in result["missing_skills"]:
        rows.append([skill, "missing", f"{weights.get(skill, 0):.0%}" if skill in weights else "-"])
    if rows:
        ui.print_table("Skills", ["Skill", "Status", "JD weight"], rows, status_col=None)
    for key, text in result["breakdown"].items():
        ui.info(f"{key}: {text}")
    if not result["matched_skills"] and not result["missing_skills"]:
        ui.warn("No recognized skills in this job description; the skills score is a neutral default, not a real match.")
    return 0
