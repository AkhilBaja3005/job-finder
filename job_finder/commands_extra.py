"""CLI commands that render through job_finder.ui: status, config, export, cover-letter, plus secret masking."""

import contextlib
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

from job_finder import ui

_SENSITIVE_PARTS = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential")


def mask_secrets(value: Any) -> Any:
    """Recursively replace values of sensitive-looking keys so profiles can be printed safely."""
    if isinstance(value, dict):
        return {
            k: ("********" if any(p in str(k).lower() for p in _SENSITIVE_PARTS) and v else mask_secrets(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


def _mask_key(key: Optional[str]) -> str:
    if not key:
        return "missing"
    return f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "configured"


def run_status(as_json: bool = False) -> int:
    from backend.job_finder_mcp.tools.profile_tools import get_profile_config_path, load_profile_data
    from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags

    # These helpers print progress lines; send them to stderr so --json stdout stays clean
    with contextlib.redirect_stdout(sys.stderr):
        master = find_master_resume_with_mac_tags()
        data = load_profile_data() or {}
    cand = data.get("candidate", {}) if isinstance(data, dict) else {}
    prefs = data.get("search_preferences", {}) if isinstance(data, dict) else {}
    info: Dict[str, Any] = {
        "gemini_api_key": _mask_key(os.getenv("GEMINI_API_KEY")),
        "master_resume": master if master and os.path.exists(master) else None,
        "profile_path": get_profile_config_path(),
        "profile_configured": bool(cand),
        "name": cand.get("name"),
        "location": cand.get("location"),
        "target_roles": prefs.get("target_roles", []),
        "target_locations": prefs.get("target_locations", []),
        "min_ats_score": prefs.get("min_ats_score_threshold", 65),
    }
    if as_json:
        ui.print_json(info)
        return 0
    rows = [
        ["Gemini API key", info["gemini_api_key"]],
        ["Master resume", info["master_resume"] or "not set (run `job-finder setup`)"],
        ["Profile", info["profile_path"] + ("" if info["profile_configured"] else "  (not configured)")],
        ["Candidate", info["name"] or "n/a"],
        ["Location", info["location"] or "n/a"],
        ["Target roles", ", ".join(info["target_roles"]) or "n/a"],
        ["Target locations", ", ".join(info["target_locations"]) or "n/a"],
        ["ATS score floor", f"{info['min_ats_score']}%"],
    ]
    ui.print_table("Job Finder status", ["Item", "Value"], rows)
    return 0


def run_config(as_json: bool = False) -> int:
    """Show where Job Finder reads and writes things (no secret values)."""
    from job_finder.logging_setup import log_file_path
    from backend.job_finder_mcp.tools.profile_tools import get_profile_config_path

    env_keys = ["GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "BREVO_API_KEY", "RESEND_API_KEY", "SMTP_USER",
                "NOTIFY_EMAIL", "BROWSER_USE_TIMEOUT", "JOB_FINDER_CDP_PORT", "JOB_FINDER_EMAIL_BATCH_SIZE"]
    info = {
        "profile": get_profile_config_path(),
        "log_file": log_file_path(),
        "tracker_csv": os.path.join(os.getcwd(), "applications_tracker", "job_applications_tracker.csv"),
        "environment": {k: ("set" if os.getenv(k) else "unset") for k in env_keys},
    }
    if as_json:
        ui.print_json(info)
        return 0
    ui.print_table("Paths", ["Item", "Location"], [["Profile", info["profile"]], ["Log file", info["log_file"]], ["Tracker CSV", info["tracker_csv"]]])
    ui.print_table("Environment", ["Variable", "State"], [[k, v] for k, v in info["environment"].items()], status_col=None)
    return 0


def export_applications(apps: List[Dict[str, Any]], out_path: str, fmt: str = "csv", status: Optional[str] = None) -> int:
    from job_finder.tracker_view import filter_apps

    selected = filter_apps(apps, status)
    fields = ["company", "job_title", "score", "status", "job_url", "updated_at", "created_at"]
    rows = [{f: a.get(f, "") for f in fields} for a in selected]
    if fmt == "json":
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, default=str)
    else:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    ui.success(f"Exported {len(rows)} application(s) to {out_path}")
    return 0


def run_cover_letter(job_title: str, company: str, jd_file: Optional[str], jd_url: Optional[str],
                     out_path: Optional[str], as_json: bool = False) -> int:
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services.cover_letter_generator import generate_structured_cover_letter
    from job_finder import ats_view

    profile = load_profile_data()
    if not profile or "candidate" not in profile:
        ui.error("No candidate profile found. Run `job-finder setup` first.")
        return 1
    jd_text = ats_view.load_jd_text(jd_file=jd_file, jd_url=jd_url) if (jd_file or jd_url) else ""
    if not jd_text.strip():
        ui.warn("No job description given (--jd-file or --jd-url); the letter will be less specific.")

    result = generate_structured_cover_letter(job_title=job_title, company=company, job_description=jd_text, candidate_profile=profile)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(result["cover_letter"].strip() + "\n")
    if as_json:
        ui.print_json(result)
    else:
        print(result["cover_letter"].strip())
        if out_path:
            ui.success(f"Saved to {out_path}")
    for warning in result.get("warnings", []):
        ui.warn(warning)
    if result["status"] == "fallback":
        return 2
    return 0
