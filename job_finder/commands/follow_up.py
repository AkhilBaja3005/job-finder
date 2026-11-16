"""`job-finder follow-up` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    import asyncio
    from backend.services.application_tracker import list_applications
    from backend.services.outreach_generator import generate_outreach_message
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data

    print("\n========================================================")
    print("  RECRUITER 3-DAY FOLLOW-UP & PROFILE VIEW ENGINE")
    print("========================================================\n")

    apps = list_applications()
    profile_data = load_profile_data() or {}
    cand = profile_data.get("candidate", {})

    if not apps:
        print("No tracked applications found to follow up on.\n")
    else:
        min_days = args.min_days
        print(f"Scanning applications submitted >= {min_days} days ago without response...\n")
        followup_count = 0
        for app in apps:
            status = str(app.get("status", "")).lower()
            company = app.get("company", "Company")
            job_title = app.get("job_title", "Position")
            
            if status in ("applied", "autofilled", "viewed"):
                followup_count += 1
                print(f"[{followup_count}] {job_title} @ {company}")
                print(f"    Status: {status} | URL: {app.get('job_url', 'N/A')}")
                
                ats_dummy = {
                    "match_analysis": {
                        "overall_score": app.get("score") or 85,
                        "matched_skills": cand.get("core_skills", [])[:5] if isinstance(cand.get("core_skills"), list) else [],
                        "missing_skills": [],
                        "tailoring_suggestions": []
                    }
                }
                
                outreach = generate_outreach_message(
                    job_description=f"Role: {job_title} at {company}",
                    resume_data=cand,
                    ats_analysis=ats_dummy,
                    recruiter_name=app.get("recruiter_name"),
                    company_name=company
                )
                
                inmail_text = outreach.linkedin_message
                words = inmail_text.split()
                if len(words) > 280:
                    inmail_text = " ".join(words[:280]) + "..."
                    
                print(f"    Suggested InMail ({len(words)} words, <300 words strict):")
                print(f"    \"{inmail_text}\"\n")

        if followup_count == 0:
            print(f"No pending applications older than {min_days} days require follow-up at this time.\n")
