"""
Career CRM & Application Pipeline MCP Tools.
"""

from typing import Dict, Any, Optional, List
from services.application_tracker import (
    list_applications,
    update_application_status,
    record_application
)

TRACKING_TOOLS_SPEC = [
    {
        "name": "track_application",
        "description": "Records or updates a job application in the user's career tracking pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_url": {
                    "type": "string",
                    "description": "The URL of the job."
                },
                "status": {
                    "type": "string",
                    "description": "Application status ('saved', 'tailored', 'applied', 'interviewing', 'offer', 'rejected').",
                    "enum": ["saved", "tailored", "applied", "interviewing", "offer", "rejected"]
                },
                "job_title": {
                    "type": "string",
                    "description": "Role title."
                },
                "company": {
                    "type": "string",
                    "description": "Company name."
                },
                "score": {
                    "type": "integer",
                    "description": "ATS match score percentage."
                },
                "token": {
                    "type": "string",
                    "description": "User auth or guest session token."
                }
            },
            "required": ["job_url", "status"]
        }
    },
    {
        "name": "list_applications",
        "description": "Retrieves the history of all tracked jobs, tailored resumes, and applications.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "User auth or guest session token."
                },
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status ('all', 'applied', 'saved', 'tailored'). Defaults to 'all'.",
                    "default": "all"
                }
            }
        }
    },
    {
        "name": "check_duplicate_application",
        "description": "Checks if the candidate has already applied to or saved a role at this company within the last 90 days to prevent duplicates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Target company name."
                },
                "job_title": {
                    "type": "string",
                    "description": "Target job title."
                },
                "token": {
                    "type": "string",
                    "description": "User auth or guest session token."
                }
            },
            "required": ["company"]
        }
    }
]


async def handle_track_application(arguments: Dict[str, Any]) -> Dict[str, Any]:
    url = arguments.get("job_url", "")
    status = arguments.get("status", "saved")
    title = arguments.get("job_title")
    company = arguments.get("company")
    score = arguments.get("score")
    token = arguments.get("token")

    success = update_application_status(
        token=token,
        job_url=url,
        new_status=status,
        job_title=title,
        company=company,
        score=score
    )
    return {
        "success": success,
        "job_url": url,
        "status": status,
        "company": company
    }


async def handle_list_applications(arguments: Dict[str, Any]) -> Dict[str, Any]:
    token = arguments.get("token")
    filter_status = arguments.get("status_filter", "all")

    apps = list_applications(token)
    if filter_status and filter_status != "all":
        apps = [a for a in apps if a.get("status") == filter_status]

    return {
        "count": len(apps),
        "applications": apps
    }


async def handle_check_duplicate_application(arguments: Dict[str, Any]) -> Dict[str, Any]:
    company = (arguments.get("company") or "").lower().strip()
    title = (arguments.get("job_title") or "").lower().strip()
    token = arguments.get("token")

    apps = list_applications(token)
    matched = []
    for a in apps:
        app_company = (a.get("company") or "").lower().strip()
        if company in app_company or app_company in company:
            matched.append(a)

    return {
        "is_duplicate": len(matched) > 0,
        "previous_applications": matched
    }
