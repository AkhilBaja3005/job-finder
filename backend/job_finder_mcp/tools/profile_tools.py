"""
Profile & Preferences Tools for Job Finder MCP Server.
Allows users/agents to save, retrieve, and update candidate profile and search preferences.
"""

import os
import json
from typing import Dict, Any, Optional
# pyrefly: ignore [missing-import]
try:
    from config.constants import resolve_workspace_root
except ImportError:
    from backend.config.constants import resolve_workspace_root

try:
    from dotenv import load_dotenv
    ws_env = os.path.join(resolve_workspace_root(), ".env")
    if os.path.exists(ws_env):
        load_dotenv(ws_env)
    elif "JOB_FINDER_ROOT" not in os.environ:
        load_dotenv()
except Exception:
    pass

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


def _checked_save_path() -> str:
    """The profile save path, refusing the shipped `.example.json` template so it never holds real data."""
    path = get_profile_save_path()
    if os.path.basename(path).endswith(".example.json"):
        raise ValueError(f"Refusing to write a candidate profile to the template file {path}")
    return path


def _is_cloud() -> bool:
    return bool(
        any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME", "SPACE_ID", "HF_SPACE_ID"))
        or os.getenv("ENVIRONMENT") == "production"
    )


def _clean_skill(item: Any) -> str:
    """Strip whitespace and the sentence-ending period a resume's skills line leaves on its last item."""
    return str(item).strip().rstrip(".").strip()


def clean_skills(value: Any) -> Any:
    """Normalise skills given as a list or as {category: [skills]}; drops empties and duplicates."""
    if isinstance(value, dict):
        return {str(k).strip(): clean_skills(v) for k, v in value.items() if isinstance(v, (list, tuple))}
    if isinstance(value, (list, tuple)):
        return list(dict.fromkeys(c for c in (_clean_skill(v) for v in value) if c))
    return value


def _normalize_link(link: str) -> str:
    link = str(link).strip()
    if link and not link.lower().startswith(("http://", "https://")):
        if link.lower().startswith(("linkedin.com", "github.com", "www.")):
            link = "https://" + link
        elif "." in link:
            link = "https://" + link
    return link


def _apply_links(candidate: Dict[str, Any], links: Any) -> None:
    """Map a resume's link list onto linkedin / github / portfolio, without clobbering values already set."""
    for raw in links or []:
        link = _normalize_link(raw)
        low = link.lower()
        if "linkedin.com" in low:
            candidate["linkedin"] = link
        elif "github.com/" in low and "github.io" not in low:
            candidate["github"] = link
        elif low.startswith("http"):
            candidate["portfolio"] = link


def normalize_experience(experience: Any) -> list:
    """Turn parsed resume `experience` entries into the profile's `work_experience` shape."""
    out = []
    for exp in experience or []:
        if not isinstance(exp, dict):
            continue
        raw_tech = exp.get("technologies") or []
        if isinstance(raw_tech, str):
            raw_tech = [t.strip() for t in raw_tech.split(",") if t.strip()]
        desc = exp.get("description", exp.get("highlights", []))
        if not isinstance(desc, list):
            desc = [str(desc)] if desc else []
        timeline = exp.get("timeline") or f"{exp.get('start_date', '')} \u2013 {exp.get('end_date', '')}".strip(" \u2013")
        out.append({
            "company": exp.get("company", ""),
            "role": exp.get("role", ""),
            "timeline": timeline,
            "technologies": raw_tech,
            "highlights": desc,
        })
    return out


def redact_profile(profile: Any) -> Any:
    """Return a copy of a profile that is safe to send back to a client: no stored portal password."""
    if not isinstance(profile, dict):
        return profile
    out = json.loads(json.dumps(profile))
    cand = out.get("candidate")
    if isinstance(cand, dict) and cand.get("portals_password"):
        cand["portals_password"] = "[stored, not shown]"
    return out


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
                "skill_categories": {
                    "type": "object",
                    "additionalProperties": {"type": "array", "items": {"type": "string"}},
                    "description": "Skills grouped by category, e.g. {'Languages': ['Python', 'SQL']}"
                },
                "work_experience": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "role": {"type": "string"},
                            "start_date": {"type": "string"},
                            "end_date": {"type": "string"},
                            "timeline": {"type": "string", "description": "Alternative to start_date / end_date, e.g. 'Dec 2024 - Aug 2026'"},
                            "technologies": {"type": "array", "items": {"type": "string"}},
                            "highlights": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["company", "role"]
                    },
                    "description": "Work history. Replaces the saved list."
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
                },
                "token": {
                    "type": "string",
                    "description": "User session token or 6-digit sync code. Required on cloud servers; saves are written only to this user's own profile."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_candidate_profile",
        "description": "Retrieves the currently saved candidate profile, search preferences, target roles, locations, timeframe, and reference details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "Optional user session token or 6-digit sync code. Required in remote/cloud environments to load user-specific profile."
                }
            }
        }
    },
    {
        "name": "sync_candidate_profile_from_resume",
        "description": "Parses a resume file (PDF, DOCX, or LaTeX) and populates candidate details, work experience, education, projects, skills, and summary. Locally this updates candidate_profile.json; on the cloud server it updates the authenticated user's own profile, rebuilding it from the stored resume when no readable file path is given.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resume_path": {
                    "type": "string",
                    "description": "Path to the resume file to parse (must be readable by the server). If omitted, locally detects the master resume; on cloud uses the resume already uploaded for the user."
                },
                "token": {
                    "type": "string",
                    "description": "Optional user session token or 6-digit sync code."
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


def save_profile_data(data: Dict[str, Any]) -> str:
    """Saves candidate profile data dict into active candidate_profile.json."""
    save_path = _checked_save_path()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return save_path


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

    # Core identity — parsed resume values always update candidate profile fields
    if resume_dict.get("name"):
        candidate["name"] = resume_dict["name"]

    if resume_dict.get("email"):
        candidate["email"] = resume_dict["email"]

    if resume_dict.get("phone"):
        candidate["phone"] = resume_dict["phone"]

    if resume_dict.get("location"):
        candidate["location"] = resume_dict["location"]

    # Links (LinkedIn, GitHub, Portfolio)
    _apply_links(candidate, resume_dict.get("links"))

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
        existing_exp_map = {
            (exp.get("company", "").strip().lower(), exp.get("role", "").strip().lower()): exp.get("technologies", [])
            for exp in candidate.get("work_experience", [])
            if isinstance(exp, dict) and exp.get("technologies")
        }
        exp_list = []
        for exp in resume_dict["experience"]:
            technologies = []
            raw_tech = exp.get("technologies") or ""
            if isinstance(raw_tech, str) and raw_tech.strip():
                technologies = [t.strip() for t in raw_tech.split(",") if t.strip()]
            elif isinstance(raw_tech, list):
                technologies = raw_tech

            # If parsed technologies are empty, fallback to existing technologies for this company/role
            if not technologies:
                key = (exp.get("company", "").strip().lower(), exp.get("role", "").strip().lower())
                technologies = existing_exp_map.get(key, [])

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
    skills_val = clean_skills(resume_dict.get("skills"))
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

    save_path = _checked_save_path()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    return merged

_CANDIDATE_ARG_KEYS = (
    "name", "email", "linkedin", "location", "gender", "ethnicity", "citizenship",
    "work_authorization", "requires_sponsorship", "veteran_status", "disability_status",
    "experience_summary",
)
_PREF_ARG_KEYS = ("target_roles", "target_locations", "timeframe", "seniority", "min_ats_score_threshold")

_UNAUTHENTICATED = {
    "success": False,
    "authenticated": False,
    "error": "UNAUTHENTICATED",
    "message": "Authentication required on cloud MCP server. Pass your session token or 6-digit sync code via header 'Authorization: Bearer <token>' or parameter 'token'.",
}


def _session_to_profile(resume_data: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a user's stored session data (web-app resume dict or full profile) into the profile shape."""
    if "candidate" in resume_data:
        prof = json.loads(json.dumps(resume_data))
        cand = prof["candidate"]
        if not cand.get("work_experience") and resume_data.get("experience"):
            cand["work_experience"] = normalize_experience(resume_data["experience"])
        cand["core_skills"] = clean_skills(cand.get("core_skills", []))
        prof.setdefault("search_preferences", {})
        return prof

    loc = resume_data.get("location", "")
    candidate: Dict[str, Any] = {
        "name": resume_data.get("name", ""),
        "email": resume_data.get("email", ""),
        "phone": resume_data.get("phone", ""),
        "location": loc,
        "linkedin": resume_data.get("linkedin", ""),
        "github": resume_data.get("github", ""),
        "portfolio": resume_data.get("portfolio", ""),
        "work_authorization": resume_data.get("work_auth", "Yes"),
        "requires_sponsorship": str(resume_data.get("sponsorship", "")).lower() in ("yes", "true", "required"),
        "core_skills": clean_skills(resume_data.get("skills", [])),
        "experience_summary": resume_data.get("summary", ""),
        # `experience` is what the web app and resume tailoring store; `work_experience` is only a legacy copy.
        "work_experience": normalize_experience(resume_data.get("experience")) or resume_data.get("work_experience") or [],
        "education": resume_data.get("education", []),
        "projects": resume_data.get("projects", []),
    }
    # Links found by the parser fill gaps only; values the user saved explicitly win.
    parsed_links: Dict[str, Any] = {}
    _apply_links(parsed_links, resume_data.get("links"))
    for key, val in parsed_links.items():
        if not candidate.get(key):
            candidate[key] = val
    if resume_data.get("linkedin"):
        candidate["linkedin"] = _normalize_link(resume_data["linkedin"])
    prefs = {
        "target_roles": resume_data.get("target_roles") or ["AI Engineer", "Software Engineer"],
        "target_locations": resume_data.get("target_locations") or ([loc] if loc else []) + ["Remote"],
        "timeframe": resume_data.get("timeframe", "past_24_hours"),
    }
    for key in ("seniority", "min_ats_score_threshold"):
        if resume_data.get(key) is not None:
            prefs[key] = resume_data[key]
    return {"candidate": candidate, "search_preferences": prefs}


def _apply_save_args(profile: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """Apply save_candidate_profile arguments onto a {candidate, search_preferences, ...} profile."""
    candidate = profile.setdefault("candidate", {})
    search_prefs = profile.setdefault("search_preferences", {})
    networking = profile.setdefault("networking_and_references", {})

    for key in _CANDIDATE_ARG_KEYS:
        if key in args:
            candidate[key] = _normalize_link(args[key]) if key == "linkedin" and args[key] else args[key]
    if "core_skills" in args:
        candidate["core_skills"] = clean_skills(args["core_skills"])
    if "skill_categories" in args:
        cats = clean_skills(args["skill_categories"])
        candidate["skill_categories"] = cats
        if isinstance(cats, dict):
            candidate["core_skills"] = list(dict.fromkeys(x for v in cats.values() for x in v))
    if "work_experience" in args:
        candidate["work_experience"] = normalize_experience(args["work_experience"])
    for key in _PREF_ARG_KEYS:
        if key in args:
            search_prefs[key] = args[key]
    if "references" in args:
        networking["saved_references"] = args["references"]
    return profile


def _profile_to_session_data(profile: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Store a profile back as the flat resume dict the web app reads, keeping fields it does not know about."""
    data = dict(previous)
    cand = profile.get("candidate", {})
    prefs = profile.get("search_preferences", {})
    for src, dst in (("name", "name"), ("email", "email"), ("phone", "phone"), ("location", "location"),
                     ("linkedin", "linkedin"), ("github", "github"), ("portfolio", "portfolio"),
                     ("experience_summary", "summary"), ("work_authorization", "work_auth"),
                     ("education", "education"), ("projects", "projects"),
                     ("gender", "gender"), ("ethnicity", "ethnicity"), ("citizenship", "citizenship"),
                     ("veteran_status", "veteran_status"), ("disability_status", "disability_status")):
        if src in cand:
            data[dst] = cand[src]
    if "requires_sponsorship" in cand:
        data["sponsorship"] = "Yes" if cand["requires_sponsorship"] else "No"
    skills = cand.get("skill_categories") or cand.get("core_skills")
    if skills:
        data["skills"] = skills
    if cand.get("work_experience") is not None:
        # Store one copy, under the key the web app and resume tailoring read; drop the legacy duplicate.
        data.pop("work_experience", None)
        data["experience"] = [
            {"company": e.get("company", ""), "role": e.get("role", ""),
             "start_date": (e.get("timeline", "").split("\u2013")[0] or "").strip(),
             "end_date": (e.get("timeline", "").split("\u2013")[-1] or "").strip() if "\u2013" in e.get("timeline", "") else "",
             "technologies": ", ".join(e.get("technologies", [])),
             "description": e.get("highlights", [])}
            for e in cand["work_experience"] if isinstance(e, dict)
        ]
    for key in _PREF_ARG_KEYS:
        if key in prefs:
            data[key] = prefs[key]
    if "references" in profile.get("networking_and_references", {}) or profile.get("networking_and_references", {}).get("saved_references"):
        data["saved_references"] = profile["networking_and_references"].get("saved_references")
    return data


def _save_session_profile(token: str, profile: Dict[str, Any]) -> None:
    # pyrefly: ignore [missing-import]
    from services.session_store import get_session_data, set_session_data
    session = get_session_data(token)
    data = _profile_to_session_data(profile, session.get("data") or {})
    set_session_data(token, data, session.get("path", ""))


async def handle_save_candidate_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    token = args.get("token")

    # Cloud: a profile is only ever written to the authenticated user's own session.
    if token or _is_cloud():
        if not token:
            return dict(_UNAUTHENTICATED)
        # pyrefly: ignore [missing-import]
        from services.session_store import get_session_data
        existing = (get_session_data(token).get("data")) or {}
        profile = _session_to_profile(existing) if existing else {"candidate": {}, "search_preferences": {}}
        profile = _apply_save_args(profile, args)
        _save_session_profile(token, profile)
        return {
            "success": True,
            "authenticated": True,
            "message": f"Successfully saved candidate profile and preferences for {profile['candidate'].get('name')}.",
            "profile": redact_profile(profile),
        }

    # Local: edit the workspace candidate_profile.json.
    current_data = load_profile_data()
    merged = _apply_save_args({
        "candidate": current_data.get("candidate", {}),
        "search_preferences": current_data.get("search_preferences", {}),
        "networking_and_references": current_data.get("networking_and_references", {}),
    }, args)

    save_path = _checked_save_path()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    return {
        "success": True,
        "message": f"Successfully saved candidate profile and preferences for {merged['candidate'].get('name')}.",
        "profile": redact_profile(merged),
    }

async def handle_get_candidate_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    token = args.get("token") or os.getenv("JOB_FINDER_USER_TOKEN")
    is_cloud = _is_cloud()

    # 1. If token is provided, resolve authenticated user-specific profile
    if token:
        try:
            # pyrefly: ignore [missing-import]
            from services.session_store import get_session_data
            session = get_session_data(token)
            resume_data = session.get("data")
            if resume_data and (resume_data.get("name") or resume_data.get("email") or resume_data.get("education") or resume_data.get("skills") or resume_data.get("candidate")):
                return {"found": True, "profile": redact_profile(_session_to_profile(resume_data)), "authenticated": True}
            return {
                "found": False,
                "authenticated": True,
                "message": "No candidate profile found for the provided session token. Please upload or sync a resume first."
            }
        except Exception as e:
            print(f"[handle_get_candidate_profile] User token session resolution notice: {e}")

    # 2. In cloud environments without an authenticated token, prevent leaking shared / stale profiles
    if is_cloud and not token:
        return {
            "found": False,
            "authenticated": False,
            "error": "UNAUTHENTICATED",
            "message": "Authentication required on cloud MCP server. Please pass your session token or 6-digit sync code via header 'Authorization: Bearer <token>' or parameter 'token'."
        }

    # 3. Local environment fallback (reads active local candidate_profile.json)
    data = load_profile_data()
    if not data:
        return {
            "found": False,
            "message": "No profile saved yet. Use save_candidate_profile to configure."
        }
    return {
        "found": True,
        "profile": redact_profile(data),
        "authenticated": bool(token)
    }

async def handle_sync_candidate_profile_from_resume(args: Dict[str, Any]) -> Dict[str, Any]:
    """Parses a resume and writes structured sections into the profile (the user's own session on cloud)."""
    # pyrefly: ignore [missing-import]
    from services.resume_parser import parse_resume

    token = args.get("token")
    cloud_mode = bool(token) or _is_cloud()
    if cloud_mode and not token:
        return dict(_UNAUTHENTICATED)

    resume_path = args.get("resume_path")

    if cloud_mode:
        # pyrefly: ignore [missing-import]
        from services.session_store import get_session_data
        session = get_session_data(token)
        stored = session.get("data") or {}
        if resume_path and os.path.exists(resume_path):
            resume_dict = parse_resume(resume_path).model_dump()
            source = resume_path
        elif stored:
            # No readable file on the server: rebuild the profile from the resume already stored for this user.
            resume_dict = dict(stored.get("candidate") or stored)
            if "experience" not in resume_dict and resume_dict.get("work_experience"):
                resume_dict["experience"] = resume_dict["work_experience"]
            source = "your stored resume"
        else:
            return {
                "success": False,
                "error": "No resume available. Upload your resume in the web app first; a file path on your own computer is not readable by the cloud server.",
            }
        profile = _session_to_profile(stored) if stored else {"candidate": {}, "search_preferences": {}}
        cand = profile.setdefault("candidate", {})
        for key in ("name", "email", "phone", "location"):
            if resume_dict.get(key):
                cand[key] = resume_dict[key]
        _apply_links(cand, resume_dict.get("links"))
        if resume_dict.get("summary"):
            cand["experience_summary"] = resume_dict["summary"]
        if resume_dict.get("education"):
            cand["education"] = resume_dict["education"]
        if resume_dict.get("projects"):
            cand["projects"] = resume_dict["projects"]
        if resume_dict.get("experience"):
            cand["work_experience"] = normalize_experience(resume_dict["experience"])
        skills = clean_skills(resume_dict.get("skills"))
        if isinstance(skills, dict) and skills:
            cand["skill_categories"] = skills
            cand["core_skills"] = list(dict.fromkeys(x for v in skills.values() for x in v))
        elif isinstance(skills, list) and skills:
            cand["core_skills"] = skills
        _save_session_profile(token, profile)
        return {
            "success": True,
            "authenticated": True,
            "message": f"Successfully synced profile from {source}.",
            "candidate_name": cand.get("name"),
            "skills_count": len(cand.get("core_skills") or []),
            "experience_count": len(cand.get("work_experience") or []),
            "education_count": len(cand.get("education") or []),
        }

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

    # Persist synced resume path into workspace .env MASTER_RESUME_PATH
    try:
        ws = resolve_workspace_root()
        env_file = os.path.join(ws, ".env")
        lines = []
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("MASTER_RESUME_PATH="):
                new_lines.append(f'MASTER_RESUME_PATH="{resume_path}"\n')
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f'MASTER_RESUME_PATH="{resume_path}"\n')
        
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        os.environ["MASTER_RESUME_PATH"] = resume_path
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Successfully synced profile from '{resume_path}' into {PROFILE_CONFIG_PATH}",
        "resume_path": resume_path,
        "candidate_name": updated_profile.get("candidate", {}).get("name"),
        "skills_count": len(updated_profile.get("candidate", {}).get("core_skills", [])),
        "experience_count": len(updated_profile.get("candidate", {}).get("work_experience", [])),
        "education_count": len(updated_profile.get("candidate", {}).get("education", []))
    }
