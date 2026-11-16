"""`job-finder profile` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    if getattr(args, "sync", None):
        import asyncio
        from backend.job_finder_mcp.tools.profile_tools import handle_sync_candidate_profile_from_resume
        resume_arg = None if args.sync == "AUTO" else args.sync
        res = asyncio.run(handle_sync_candidate_profile_from_resume({"resume_path": resume_arg}))
        if res.get("success"):
            print(f"{res.get('message')}")
            print(f"Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
        else:
            print(f"Sync failed: {res.get('error')}")
        return

    from backend.job_finder_mcp.tools.profile_tools import get_profile_config_path, load_profile_data
    prof_path = get_profile_config_path()
    data = load_profile_data()
    if data:
        from job_finder.commands_extra import mask_secrets
        ui.info(f"Profile: {prof_path}")
        print(json.dumps(mask_secrets(data), indent=2))
    else:
        print(f"Candidate profile not found. Run `job-finder setup` to initialize one at: {prof_path}")
