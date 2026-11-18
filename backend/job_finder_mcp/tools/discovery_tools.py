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
        "description": "Searches Ashby, Greenhouse, Lever, LinkedIn, and Indeed for matching jobs and returns scored listings. Results are compact (descriptions are shortened); call scrape_job_posting with a job's url for the full text.",
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum jobs to return, best scores first (default 25, max 100). Use scrape_job_posting for a job's full description.",
                    "default": 25,
                    "minimum": 1,
                    "maximum": 100
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


from job_finder_mcp.tools.profile_tools import load_profile_data

DEFAULT_RESULT_LIMIT = 25
MAX_RESULT_LIMIT = 100
MAX_TEXT_CHARS = 300          # longest text field kept per job
MAX_PAYLOAD_CHARS = 60_000    # a tool result larger than this overflows most clients


def _shorten(value: Any, limit: int = MAX_TEXT_CHARS) -> Any:
    """Cut long strings (job descriptions) so one listing stays small; recurse into lists and dicts."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit].rstrip() + "\u2026"
    if isinstance(value, list):
        return [_shorten(v, limit) for v in value[:20]]
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    return value


def _compact_results(jobs: list, est_jobs: list, limit: int) -> tuple:
    """Return at most `limit` shortened jobs, trimmed further if the JSON would still be too large."""
    kept = [_shorten(j) for j in jobs[:limit]]
    est = [_shorten(j) for j in est_jobs[:10]]
    while kept and len(json.dumps({"jobs": kept, "est_jobs": est}, default=str)) > MAX_PAYLOAD_CHARS:
        kept.pop()
    while est and len(json.dumps({"jobs": kept, "est_jobs": est}, default=str)) > MAX_PAYLOAD_CHARS:
        est.pop()
    return kept, est

async def handle_search_jobs(arguments: Dict[str, Any]) -> Dict[str, Any]:
    prof_data = load_profile_data()
    cand = prof_data.get("candidate", {})
    prefs = prof_data.get("search_preferences", {})

    target_roles = prefs.get("target_roles", ["AI Engineer", "Agentic AI Engineer", "LLM Engineer", "Machine Learning Engineer", "Senior AI Engineer", "Applied AI Scientist"])
    default_keywords = ", ".join(target_roles)

    keywords_arg = arguments.get("keywords")
    if isinstance(keywords_arg, list):
        keywords = ", ".join(str(k) for k in keywords_arg if k)
    elif keywords_arg:
        keywords = str(keywords_arg)
    else:
        keywords = default_keywords
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

    exclude_portals = arguments.get("exclude_portals")

    jobs = []
    est_jobs = []
    try:
        partial_jobs = []
        async for chunk in find_matching_jobs(
            resume_data=resume_data,
            location=location,
            keywords=keywords,
            timeframe=timeframe,
            exclude_portals=exclude_portals
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

    try:
        limit = int(arguments.get("limit") or DEFAULT_RESULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_RESULT_LIMIT
    limit = max(1, min(limit, MAX_RESULT_LIMIT))

    kept, est = _compact_results(jobs, est_jobs, limit)
    result = {
        "count": len(jobs),
        "returned": len(kept),
        "location": location,
        "timeframe": timeframe,
        "jobs": kept,
        "est_jobs": est,
    }
    if len(kept) < len(jobs):
        result["note"] = f"Showing {len(kept)} of {len(jobs)} jobs. Pass a larger limit (max {MAX_RESULT_LIMIT}) or narrower keywords; use scrape_job_posting for full descriptions."
    return result


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


async def handle_company_culture_brief(arguments: Dict[str, Any]) -> Dict[str, Any]:
    company = arguments.get("company", "")
    if not company:
        return {"error": "Missing required argument 'company'"}
    role = arguments.get("role", "Software Engineer")

    from services.agent_reach_service import generate_enhanced_company_brief
    return await asyncio.to_thread(generate_enhanced_company_brief, company, role)
