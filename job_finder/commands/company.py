"""`job-finder company` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from backend.services.agent_reach_service import generate_enhanced_company_brief
    print(f"⏳ Fetching Agent-Reach community culture brief for '{args.name}'...")
    res = generate_enhanced_company_brief(args.name, args.role)
    if res.get("status") == "success":
        print(f"\n========================================================")
        print(f"    AGENT-REACH COMPANY BRIEF: {args.name.upper()} ({args.role})")
        print("========================================================\n")
        print(res.get("brief_markdown", ""))
    else:
        print(f"Could not fetch company brief: {res.get('message')}")
