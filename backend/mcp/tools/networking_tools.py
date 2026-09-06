"""
Recruiter Intelligence & Cold Outreach MCP Tools.
"""

from typing import Dict, Any, Optional
from services.recruiter_extractor import extract_recruiter
from services.outreach_generator import generate_outreach_message
from services.session_store import get_session_data
from mcp.tools.profile_tools import load_profile_data

NETWORKING_TOOLS_SPEC = [
    {
        "name": "extract_recruiter_profile",
        "description": "Extracts recruiter or hiring manager name and LinkedIn profile URL from a job listing page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_url": {
                    "type": "string",
                    "description": "The URL of the job posting."
                },
                "platform": {
                    "type": "string",
                    "description": "Target platform (e.g. 'linkedin', 'indeed'). Defaults to 'linkedin'.",
                    "default": "linkedin"
                }
            },
            "required": ["job_url"]
        }
    },
    {
        "name": "generate_outreach_inmail",
        "description": "Generates a personalized, high-converting 3-sentence recruiter outreach message or cold InMail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_title": {
                    "type": "string",
                    "description": "Target role title."
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name."
                },
                "recruiter_name": {
                    "type": "string",
                    "description": "Name of the recruiter or hiring manager if known."
                },
                "job_description": {
                    "type": "string",
                    "description": "Target job description excerpt."
                },
                "candidate_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of candidate's core matching skills."
                }
            },
            "required": ["job_title", "company_name"]
        }
    }
]


async def handle_extract_recruiter_profile(arguments: Dict[str, Any]) -> Dict[str, Any]:
    url = arguments.get("job_url", "")
    platform = arguments.get("platform", "linkedin")
    res = await extract_recruiter(url, platform=platform)
    return {
        "recruiter_name": res.get("recruiter_name"),
        "recruiter_profile_url": res.get("recruiter_profile_url"),
        "found": bool(res.get("recruiter_name") or res.get("recruiter_profile_url"))
    }


async def handle_generate_outreach_inmail(arguments: Dict[str, Any]) -> Dict[str, Any]:
    title = arguments.get("job_title", "Software Engineer")
    company = arguments.get("company_name", "Hiring Company")
    recruiter = arguments.get("recruiter_name")
    jd = arguments.get("job_description", "")
    prof = load_profile_data()
    cand = prof.get("candidate", {})
    cand_name = cand.get("name", "Akhil Baja")
    raw_skills = arguments.get("candidate_skills")
    skills = raw_skills if raw_skills else cand.get("core_skills", ["Agentic AI", "LLM Systems", "RAG"])

    try:
        res = generate_outreach_message(
            job_description=jd or f"Role: {title} at {company}",
            resume_data={"name": cand_name, "skills": skills},
            ats_analysis={},
            recruiter_name=recruiter,
            company_name=company
        )
        msg = (res.linkedin_message or res.email_body) if res else ""
        if not msg or "background in  aligns" in msg:
            skills_str = ", ".join(skills[:3]) if skills else "Agentic AI and RAG pipelines"
            msg = f"Hi {recruiter or 'Hiring Team'},\n\nI noticed the {title} opening at {company} and wanted to reach out. As a Senior AI Engineer, I architected production {skills_str} handling over 2M queries/day with <150ms latency. Would you be open to a brief chat if my background aligns with what the team is looking for?\n\nBest regards,\n{cand_name}"
    except Exception:
        skills_str = ", ".join(skills[:3]) if skills else "Agentic AI and RAG pipelines"
        msg = f"Hi {recruiter or 'Hiring Team'},\n\nI noticed the {title} opening at {company} and wanted to reach out. As a Senior AI Engineer, I architected production {skills_str} handling over 2M queries/day with <150ms latency. Would you be open to a brief chat if my background aligns with what the team is looking for?\n\nBest regards,\n{cand_name}"

    return {
        "message": msg,
        "recipient": recruiter or "Hiring Team",
        "word_count": len(msg.split())
    }
