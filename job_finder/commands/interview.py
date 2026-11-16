"""`job-finder interview` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from backend.services.session_store import get_session_data
    from backend.services.gemini_client import generate_content_with_fallback
    from backend.services.agent_reach_service import extract_youtube_transcript

    session = get_session_data("guest")
    cand_data = session.get("data", {})
    
    yt_transcript = ""
    if args.youtube:
        print(f"Parsing YouTube interview transcript from: {args.youtube}...")
        yt_res = extract_youtube_transcript(args.youtube)
        if yt_res.get("status") == "success":
            yt_transcript = yt_res.get("transcript", "")
            print(f"Extracted {len(yt_transcript)} chars of technical interview transcript via {yt_res.get('source')}.")

    prompt = f"""You are a professional Interview Coach.
Generate a custom Interview Prep Pack for candidate applying to '{args.role}' at '{args.company}'.

CANDIDATE DATA:
{json.dumps(cand_data, indent=2)}

{"YOUTUBE TECHNICAL INTERVIEW TRANSCRIPT: " + yt_transcript[:2000] if yt_transcript else ""}

Output Markdown with 4 sections:
1. Behavioral STAR Q&A
2. Technical Review Checklist
3. Tough Questions ('Why this company?')
4. Smart Questions to Ask Interviewers"""

    print(f"Generating Interview Prep Pack for {args.company}...")
    prep_md = generate_content_with_fallback(prompt, model_tier="lite")
    print(f"\n========================================================")
    print(f"    INTERVIEW PREP PACK: {args.company.upper()} ({args.role})")
    print("========================================================\n")
    print(prep_md)
