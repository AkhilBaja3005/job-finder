"""
Deterministic ATS Match & Skill Gap MCP Tools.
"""

from typing import Dict, Any, Optional
from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
from services.job_searcher import _extract_salary_and_seniority
from services.session_store import get_session_data

ATS_TOOLS_SPEC = [
    {
        "name": "calculate_ats_score",
        "description": "Calculates deterministic ATS compatibility scores between a resume and job description text or URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_description": {
                    "type": "string",
                    "description": "The full text of the job description."
                },
                "resume_data": {
                    "type": "object",
                    "description": "Candidate structured resume JSON (skills, experience, education). If omitted, uses active session token."
                },
                "token": {
                    "type": "string",
                    "description": "User or guest token to load candidate profile."
                }
            },
            "required": ["job_description"]
        }
    },
    {
        "name": "analyze_skill_gap",
        "description": "Performs in-depth skill taxonomy comparison to identify exact matched skills, missing keywords, and recommended additions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_description": {
                    "type": "string",
                    "description": "Target job description text."
                },
                "resume_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of skills currently on the candidate's resume."
                }
            },
            "required": ["job_description"]
        }
    },
    {
        "name": "extract_seniority_salary",
        "description": "Extracts compensation range figures and seniority levels from job descriptions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The job description or posting text."
                },
                "title": {
                    "type": "string",
                    "description": "Job title (e.g. 'Lead Cloud Engineer')."
                }
            },
            "required": ["text"]
        }
    }
]


from mcp.tools.profile_tools import load_profile_data

async def handle_calculate_ats_score(arguments: Dict[str, Any]) -> Dict[str, Any]:
    jd = arguments.get("job_description", "")
    resume_data = arguments.get("resume_data")
    token = arguments.get("token")

    if not resume_data and token:
        session = get_session_data(token)
        resume_data = session.get("data") or {}

    if not resume_data:
        prof = load_profile_data()
        cand = prof.get("candidate", {})
        if cand:
            resume_data = {
                "name": cand.get("name", "Akhil Baja"),
                "location": cand.get("location", "London, UK"),
                "skills": cand.get("core_skills", []),
                "experience": [
                    {
                        "role": exp.get("role", ""),
                        "company": exp.get("company", ""),
                        "start_date": exp.get("timeline", "").split("–")[0].strip() if "–" in exp.get("timeline", "") else exp.get("timeline", "").split("-")[0].strip(),
                        "end_date": exp.get("timeline", "").split("–")[1].strip() if "–" in exp.get("timeline", "") else (exp.get("timeline", "").split("-")[1].strip() if "-" in exp.get("timeline", "") else "Present"),
                        "description": exp.get("highlights", [])
                    }
                    for exp in cand.get("work_experience", [])
                ] if cand.get("work_experience") else [
                    {
                        "role": "Software Engineer (GenAI / Systems)",
                        "company": "Qualcomm",
                        "start_date": "Dec 2024",
                        "end_date": "Aug 2026",
                        "description": [cand.get("experience_summary", "")]
                    }
                ],
                "education": cand.get("education", []),
                "projects": cand.get("projects", [])
            }
        else:
            resume_data = {}

    ats = compute_ats_score(resume_data, jd)
    role_fit = estimate_role_fit_score(resume_data, jd)
    overall = compute_overall_score(ats.skills_score, ats.experience_score, role_fit)

    return {
        "overall_score": overall,
        "skills_score": ats.skills_score,
        "experience_score": ats.experience_score,
        "role_fit_score": role_fit,
        "eligible": ats.eligible,
        "knockout_reason": ats.knockout_reason,
        "matched_skills": ats.matched_skills,
        "missing_skills": ats.missing_skills,
        "candidate_years": ats.candidate_years,
        "required_years": ats.required_years
    }


async def handle_analyze_skill_gap(arguments: Dict[str, Any]) -> Dict[str, Any]:
    jd = arguments.get("job_description", "")
    skills = arguments.get("resume_skills", [])
    if not skills:
        prof = load_profile_data()
        cand = prof.get("candidate", {})
        skills = cand.get("core_skills", [])

    resume_data = {"skills": skills}
    ats = compute_ats_score(resume_data, jd)

    return {
        "matched_skills": ats.matched_skills,
        "missing_skills": ats.missing_skills,
        "match_percentage": ats.skills_score,
        "total_jd_skills_detected": len(ats.matched_skills) + len(ats.missing_skills)
    }


async def handle_extract_seniority_salary(arguments: Dict[str, Any]) -> Dict[str, Any]:
    text = arguments.get("text", "")
    title = arguments.get("title", "")
    meta = _extract_salary_and_seniority(text, title)
    return {
        "seniority": meta.get("seniority"),
        "salary": meta.get("salary")
    }
