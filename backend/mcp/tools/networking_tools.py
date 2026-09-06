"""
Recruiter Intelligence & Cold Outreach MCP Tools.
"""

from typing import Dict, Any, Optional
from services.recruiter_extractor import extract_recruiter
from services.outreach_generator import generate_outreach_message
from services.session_store import get_session_data

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
    skills = arguments.get("candidate_skills", [])

    try:
        res = generate_outreach_message(
            job_description=jd or f"Role: {title} at {company}",
            resume_data={"skills": skills},
            ats_analysis={},
            recruiter_name=recruiter,
            company_name=company
        )
        msg = res.linkedin_message or res.email_body
    except Exception:
        skills_str = ", ".join(skills[:3]) if skills else "software engineering"
        msg = f"Hi {recruiter or 'Hiring Team'},\n\nI noticed the {title} opening at {company} and wanted to introduce myself. With deep hands-on expertise in {skills_str}, I have built and scaled systems solving similar challenges. Would you be open to a brief chat if my background aligns with what the team is looking for?\n\nBest regards,\nCandidate"

    return {
        "message": msg,
        "recipient": recruiter or "Hiring Team",
        "word_count": len(msg.split())
    }
