"""
Profile & Preferences Tools for Job Finder MCP Server.
Allows users/agents to save, retrieve, and update candidate profile and search preferences.
"""

import os
import json
from typing import Dict, Any, Optional
# pyrefly: ignore [missing-import]
from config.constants import resolve_workspace_root

def get_profile_config_path() -> str:
    """
    Finds the candidate_profile.json to read.
    Prioritizes the active workspace directory so user profiles are never tied to .venv.
    """
    custom = os.getenv("CANDIDATE_PROFILE_PATH")
    if custom and os.path.exists(custom):
        return custom

    ws = resolve_workspace_root()
    ws_candidates = [
        os.path.join(ws, "candidate_profile.json"),
        os.path.join(ws, "backend", "config", "candidate_profile.json"),
        os.path.join(ws, "config", "candidate_profile.json"),
    ]
    for p in ws_candidates:
        if os.path.exists(p):
            return p

    # Fallback to package template / defaults
    pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pkg_candidates = [
        os.path.join(pkg_root, "config", "candidate_profile.json"),
        os.path.join(pkg_root, "backend", "config", "candidate_profile.json"),
        os.path.join(pkg_root, "config", "candidate_profile.example.json"),
        os.path.join(pkg_root, "backend", "config", "candidate_profile.example.json"),
    ]
    for p in pkg_candidates:
        if os.path.exists(p):
            return p

    return os.path.join(ws, "candidate_profile.json")

def get_profile_save_path() -> str:
    """
    Returns the target path to save candidate profile updates.
    Always writes to the active workspace to prevent modifying library files in .venv.
    """
    custom = os.getenv("CANDIDATE_PROFILE_PATH")
    if custom:
        return custom

    ws = resolve_workspace_root()
    # If workspace has backend/config/candidate_profile.json (e.g. source repo), save there
    ws_backend_cfg = os.path.join(ws, "backend", "config", "candidate_profile.json")
    if os.path.exists(ws_backend_cfg):
        return ws_backend_cfg
    ws_cfg = os.path.join(ws, "candidate_profile.json")
    if os.path.exists(ws_cfg):
        return ws_cfg
    # If in source repo root
    if os.path.isdir(os.path.join(ws, "backend", "config")):
        return ws_backend_cfg
    return ws_cfg

PROFILE_CONFIG_PATH = get_profile_config_path()


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
                "gender": {"type": "string", "description": "Candidate gender (e.g. 'Male', 'Female', 'Decline to self-identify')"},
                "ethnicity": {"type": "string", "description": "Candidate ethnicity / race category (e.g. 'Asian', 'White', 'Hispanic', etc.)"},
                "citizenship": {"type": "string", "description": "Candidate nationality / primary citizenship"},
                "work_authorization": {"type": "string", "description": "Current work authorization status details"},
                "requires_sponsorship": {"type": "boolean", "description": "Whether visa sponsorship is required"},
                "veteran_status": {"type": "string", "description": "Veteran status (e.g. 'No', 'I am not a protected veteran')"},
                "disability_status": {"type": "string", "description": "Disability status (e.g. 'No, I do not have a disability')"},
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
    },
    {
        "name": "sync_candidate_profile_from_resume",
        "description": "Parses a resume file (PDF, DOCX, or LaTeX) and automatically populates candidate details, work experience, education, projects, skills, and summary in candidate_profile.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resume_path": {
                    "type": "string",
                    "description": "Path to the resume file to parse. If omitted, automatically detects the master resume."
                }
            }
        }
    }
]

def load_profile_data() -> Dict[str, Any]:
    cfg_path = get_profile_config_path()
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    example_path = cfg_path.replace("candidate_profile.json", "candidate_profile.example.json")
    if os.path.exists(example_path):
        try:
            with open(example_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def sync_resume_data_to_profile(resume_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies structured resume fields into candidate_profile.json, preserving
    existing demographic / security fields (like portals_password, work_authorization)
    while refreshing work experience, education, projects, skills, and summary.
    """
    current_data = load_profile_data()
    candidate = current_data.setdefault("candidate", {})
    search_prefs = current_data.setdefault("search_preferences", {})
    networking = current_data.setdefault("networking_and_references", {})

    # Core identity — parsed resume values always supersede empty values or template placeholders
    placeholder_names = {"jane doe", "john doe", "candidate name", "your name"}
    placeholder_emails = {"jane.doe@example.com", "candidate@example.com", "email@example.com"}
    placeholder_locations = {"ec1a 1bb"}

    if resume_dict.get("name"):
        cur_name = (candidate.get("name") or "").strip().lower()
        if not candidate.get("name") or cur_name in placeholder_names:
            candidate["name"] = resume_dict["name"]

    if resume_dict.get("email"):
        cur_email = (candidate.get("email") or "").strip().lower()
        if not candidate.get("email") or cur_email in placeholder_emails:
            candidate["email"] = resume_dict["email"]

    if resume_dict.get("phone"):
        cur_phone = (candidate.get("phone") or "").strip()
        if not candidate.get("phone") or "+44 7123" in cur_phone:
            candidate["phone"] = resume_dict["phone"]

    if resume_dict.get("location") and not candidate.get("location"):
        candidate["location"] = resume_dict["location"]

    # Links (LinkedIn, GitHub, Portfolio)
    links = resume_dict.get("links") or []
    for link in links:
        link_str = str(link).strip()
        cur_linkedin = (candidate.get("linkedin") or "").lower()
        cur_github = (candidate.get("github") or "").lower()
        cur_portfolio = (candidate.get("portfolio") or "").lower()

        if "linkedin.com" in link_str and (not candidate.get("linkedin") or "janedoe" in cur_linkedin):
            candidate["linkedin"] = link_str
        elif "github.com" in link_str and (not candidate.get("github") or "janedoe" in cur_github):
            candidate["github"] = link_str
        elif ("http" in link_str or ".io" in link_str) and (not candidate.get("portfolio") or "janedoe" in cur_portfolio):
            candidate["portfolio"] = link_str

    # Summary
    if resume_dict.get("summary"):
        candidate["experience_summary"] = resume_dict["summary"]

    # Education
    if resume_dict.get("education"):
        edu_list = []
        for e in resume_dict["education"]:
            deg = (e.get("degree") or "").strip()
            field = (e.get("field_of_study") or "").strip()
            if field and field.lower() not in deg.lower():
                deg_full = f"{deg} in {field}" if deg else field
            else:
                deg_full = deg

            edu_entry = {
                "institution": e.get("institution", ""),
                "degree": deg_full,
                "timeline": f"{e.get('start_date', '')} - {e.get('graduation_date', '')}".strip(" -"),
                "location": e.get("location", ""),
            }
            if e.get("gpa"):
                edu_entry["cpi"] = str(e["gpa"])
            if e.get("highlights"):
                edu_entry["highlights"] = e["highlights"]
            edu_list.append(edu_entry)
        candidate["education"] = edu_list

    # Work Experience
    if resume_dict.get("experience"):
        exp_list = []
        for exp in resume_dict["experience"]:
            technologies = []
            raw_tech = exp.get("technologies") or ""
            if isinstance(raw_tech, str) and raw_tech.strip():
                technologies = [t.strip() for t in raw_tech.split(",") if t.strip()]
            elif isinstance(raw_tech, list):
                technologies = raw_tech

            exp_list.append({
                "company": exp.get("company", ""),
                "role": exp.get("role", ""),
                "timeline": f"{exp.get('start_date', '')} – {exp.get('end_date', '')}".strip(" –"),
                "technologies": technologies,
                "highlights": exp.get("description", []) if isinstance(exp.get("description"), list) else [str(exp.get("description", ""))]
            })
        candidate["work_experience"] = exp_list

    # Projects
    if resume_dict.get("projects"):
        proj_list = []
        for p in resume_dict["projects"]:
            raw_tech = p.get("technologies") or []
            if isinstance(raw_tech, str):
                technologies = [t.strip() for t in raw_tech.split(",") if t.strip()]
            elif isinstance(raw_tech, list):
                technologies = raw_tech
            else:
                technologies = []

            desc = p.get("description", "")
            if isinstance(desc, list):
                desc_str = " ".join(desc)
            else:
                desc_str = str(desc)

            proj_list.append({
                "title": p.get("title", ""),
                "category": p.get("category") or "GenAI / Systems",
                "technologies": technologies,
                "url": p.get("url", ""),
                "description": desc_str
            })
        candidate["projects"] = proj_list

    # Skills & Skill Categories
    skills_val = resume_dict.get("skills")
    if isinstance(skills_val, dict):
        candidate["skill_categories"] = skills_val
        all_skills = []
        for cat_skills in skills_val.values():
            if isinstance(cat_skills, list):
                all_skills.extend(cat_skills)
        candidate["core_skills"] = list(dict.fromkeys(all_skills))
    elif isinstance(skills_val, list):
        candidate["core_skills"] = list(dict.fromkeys(skills_val))

    merged = {
        "candidate": candidate,
        "search_preferences": search_prefs,
        "networking_and_references": networking
    }

    save_path = get_profile_save_path()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    return merged

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
    if "gender" in args: candidate["gender"] = args["gender"]
    if "ethnicity" in args: candidate["ethnicity"] = args["ethnicity"]
    if "citizenship" in args: candidate["citizenship"] = args["citizenship"]
    if "work_authorization" in args: candidate["work_authorization"] = args["work_authorization"]
    if "requires_sponsorship" in args: candidate["requires_sponsorship"] = args["requires_sponsorship"]
    if "veteran_status" in args: candidate["veteran_status"] = args["veteran_status"]
    if "disability_status" in args: candidate["disability_status"] = args["disability_status"]
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

    save_path = get_profile_save_path()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
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

async def handle_sync_candidate_profile_from_resume(args: Dict[str, Any]) -> Dict[str, Any]:
    """Parses resume file and writes structured sections into candidate_profile.json."""
    # pyrefly: ignore [missing-import]
    from services.resume_parser import parse_resume

    resume_path = args.get("resume_path")
    if not resume_path:
        # Check master resume fallback
        try:
            # pyrefly: ignore [missing-import]
            from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags  # type: ignore
            resume_path = find_master_resume_with_mac_tags()
        except Exception:
            pass

    if not resume_path or not os.path.exists(resume_path):
        return {
            "success": False,
            "error": f"Resume file not found at '{resume_path}'"
        }

    structured = parse_resume(resume_path)
    resume_dict = structured.model_dump()
    updated_profile = sync_resume_data_to_profile(resume_dict)

    return {
        "success": True,
        "message": f"Successfully synced profile from '{resume_path}' into {PROFILE_CONFIG_PATH}",
        "resume_path": resume_path,
        "candidate_name": updated_profile.get("candidate", {}).get("name"),
        "skills_count": len(updated_profile.get("candidate", {}).get("core_skills", [])),
        "experience_count": len(updated_profile.get("candidate", {}).get("work_experience", [])),
        "education_count": len(updated_profile.get("candidate", {}).get("education", []))
    }

