"""
Discovery & Scraping MCP Tools.
Enables agents to search and scrape Ashby, Greenhouse, Lever, LinkedIn, and Indeed.
"""

import os
import asyncio
import json
from typing import Dict, Any, Optional, List
from services.job_searcher import find_matching_jobs
from services.scraper import scrape_job_description
from services.session_store import get_session_data

DISCOVERY_TOOLS_SPEC = [
    {
        "name": "search_jobs",
        "description": "Searches Ashby, Greenhouse, Lever, LinkedIn, and Indeed for matching jobs and returns scored listings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Target job keywords (e.g. 'Senior Python Engineer', 'Machine Learning')."
                },
                "location": {
                    "type": "string",
                    "description": "Target location (e.g. 'London', 'Remote', 'New York'). Defaults to 'Remote'.",
                    "default": "Remote"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Recency timeframe ('24h', '48h', 'week', 'all'). Defaults to '48h'.",
                    "default": "48h"
                },
                "token": {
                    "type": "string",
                    "description": "Optional user or guest token to score against candidate's active resume."
                }
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "scrape_job_posting",
        "description": "Deep-scrapes any job posting URL to extract cleaned description, company name, requirements, and recruiter details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The HTTP/HTTPS job posting link to scrape."
                }
            },
            "required": ["url"]
        }
    }
]


from mcp.tools.profile_tools import load_profile_data

async def handle_search_jobs(arguments: Dict[str, Any]) -> Dict[str, Any]:
    prof_data = load_profile_data()
    cand = prof_data.get("candidate", {})
    prefs = prof_data.get("search_preferences", {})

    target_roles = prefs.get("target_roles", ["AI Engineer", "Agentic AI Engineer", "LLM Engineer", "Machine Learning Engineer", "Senior AI Engineer", "Applied AI Scientist"])
    default_keywords = ", ".join(target_roles)

    keywords = arguments.get("keywords") or default_keywords
    location = arguments.get("location") or (prefs.get("target_locations", ["London, UK"])[0])
    timeframe = arguments.get("timeframe") or "24h"
    token = arguments.get("token")

    resume_data = {}
    if token:
        session = get_session_data(token)
        resume_data = session.get("data") or {}
    
    if not resume_data and cand:
        formatted_experience = []
        for exp in cand.get("work_experience", []):
            timeline = exp.get("timeline", "")
            parts = timeline.split("–") if "–" in timeline else timeline.split("-")
            start = parts[0].strip() if len(parts) > 0 else "2023"
            end = parts[1].strip() if len(parts) > 1 else "Present"
            formatted_experience.append({
                "role": exp.get("role", "Engineer"),
                "company": exp.get("company", "Tech"),
                "start_date": start,
                "end_date": end,
                "description": exp.get("highlights", [])
            })
        if not formatted_experience:
            formatted_experience = [{
                "role": "Senior AI Engineer",
                "company": "Tech Solutions",
                "start_date": "June 2023",
                "end_date": "Present",
                "description": [cand.get("experience_summary", "")]
            }]

        resume_data = {
            "name": cand.get("name"),
            "location": cand.get("location", "London, UK"),
            "requires_sponsorship": cand.get("requires_sponsorship", True),
            "skills": cand.get("core_skills", []),
            "education": cand.get("education", []),
            "experience": formatted_experience
        }

    jobs = []
    est_jobs = []
    try:
        partial_jobs = []
        async for chunk in find_matching_jobs(
            resume_data=resume_data,
            location=location,
            keywords=keywords,
            timeframe=timeframe
        ):
            if not chunk or not chunk.strip():
                continue
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "result":
                        res_jobs = data.get("jobs", [])
                        if res_jobs:
                            jobs = res_jobs
                        else:
                            jobs = partial_jobs
                        est_jobs = data.get("est_jobs", [])
                    elif data.get("type") == "partial_result" and "job" in data:
                        partial_jobs.append(data["job"])
                except Exception:
                    pass
            if jobs:
                break
        if not jobs and partial_jobs:
            jobs = partial_jobs
    except Exception as e:
        print(f"[handle_search_jobs] Error during job search: {e}")

    is_cloud = any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME", "SPACE_ID", "HF_SPACE_ID")) or os.getenv("ENVIRONMENT") == "production"
    job_slice_limit = 25 if is_cloud else 120
    est_slice_limit = 10 if is_cloud else 50

    return {
        "count": len(jobs),
        "location": location,
        "timeframe": timeframe,
        "jobs": jobs[:job_slice_limit],
        "est_jobs": est_jobs[:est_slice_limit]
    }


async def handle_scrape_job_posting(arguments: Dict[str, Any]) -> Dict[str, Any]:
    url = arguments.get("url", "")
    if not url:
        return {"error": "Missing required argument 'url'"}

    scraped = await scrape_job_description(url)
    return {
        "title": scraped.get("title"),
        "company": scraped.get("company"),
        "description": scraped.get("description"),
        "recruiter_name": scraped.get("recruiter_name"),
        "recruiter_profile_url": scraped.get("recruiter_profile_url"),
        "url": url
    }
