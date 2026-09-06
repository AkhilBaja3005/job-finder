"""
Profile & Preferences Tools for Job Finder MCP Server.
Allows users/agents to save, retrieve, and update candidate profile and search preferences.
"""

import os
import json
from typing import Dict, Any, Optional

PROFILE_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "candidate_profile.json"
)

PROFILE_TOOLS_SPEC = [
    {
        "name": "save_candidate_profile",
        "description": "Saves or updates the user's candidate profile, search preferences (target roles, locations, timeframe, min ATS score), and reference strategy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Candidate full name"},
                "email": {"type": "string", "description": "Candidate email address"},
                "linkedin": {"type": "string", "description": "LinkedIn profile URL"},
                "location": {"type": "string", "description": "Current home/base location (e.g. 'London, UK')"},
                "target_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of desired job titles (e.g. ['AI Engineer', 'LLM Engineer'])"
                },
                "target_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of target locations/modes (e.g. ['London, UK', 'Remote'])"
                },
                "timeframe": {
                    "type": "string",
                    "description": "Search freshness window e.g. 'past_24_hours', 'past_week', 'all'"
                },
                "seniority": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target seniority levels e.g. ['Mid-Level', 'Senior', 'Lead']"
                },
                "min_ats_score_threshold": {
                    "type": "number",
                    "description": "Minimum acceptable ATS compatibility score (e.g. 65)"
                },
                "core_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of top technical skills / stack"
                },
                "experience_summary": {
                    "type": "string",
                    "description": "Short bio or professional summary"
                },
                "references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "company": {"type": "string"},
                            "tier": {"type": "string"},
                            "contact": {"type": "string"}
                        }
                    },
                    "description": "Optional list of reference contacts and tiers"
                }
            },
            "required": ["name", "email", "target_roles", "target_locations"]
        }
    },
    {
        "name": "get_candidate_profile",
        "description": "Retrieves the currently saved candidate profile, search preferences, target roles, locations, timeframe, and reference details.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

def load_profile_data() -> Dict[str, Any]:
    if os.path.exists(PROFILE_CONFIG_PATH):
        try:
            with open(PROFILE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

async def handle_save_candidate_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    current_data = load_profile_data()
    candidate = current_data.get("candidate", {})
    search_prefs = current_data.get("search_preferences", {})
    networking = current_data.get("networking_and_references", {})

    # Update candidate fields
    if "name" in args: candidate["name"] = args["name"]
    if "email" in args: candidate["email"] = args["email"]
    if "linkedin" in args: candidate["linkedin"] = args["linkedin"]
    if "location" in args: candidate["location"] = args["location"]
    if "core_skills" in args: candidate["core_skills"] = args["core_skills"]
    if "experience_summary" in args: candidate["experience_summary"] = args["experience_summary"]

    # Update search preferences
    if "target_roles" in args: search_prefs["target_roles"] = args["target_roles"]
    if "target_locations" in args: search_prefs["target_locations"] = args["target_locations"]
    if "timeframe" in args: search_prefs["timeframe"] = args["timeframe"]
    if "seniority" in args: search_prefs["seniority"] = args["seniority"]
    if "min_ats_score_threshold" in args: search_prefs["min_ats_score_threshold"] = args["min_ats_score_threshold"]

    # Update references
    if "references" in args:
        networking["saved_references"] = args["references"]

    merged = {
        "candidate": candidate,
        "search_preferences": search_prefs,
        "networking_and_references": networking
    }

    os.makedirs(os.path.dirname(PROFILE_CONFIG_PATH), exist_ok=True)
    with open(PROFILE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    return {
        "success": True,
        "message": f"Successfully saved candidate profile and preferences for {candidate.get('name')}.",
        "profile": merged
    }

async def handle_get_candidate_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    data = load_profile_data()
    if not data:
        return {
            "found": False,
            "message": "No profile saved yet. Use save_candidate_profile to configure."
        }
    return {
        "found": True,
        "profile": data
    }
