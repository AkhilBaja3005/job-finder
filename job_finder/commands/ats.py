"""`job-finder ats` command."""

import argparse
import contextlib
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data, save_profile_data
    from backend.services.ats_scorer import evaluate_master_resume

    target_data = None
    if args.resume and os.path.exists(args.resume):
        from backend.services.resume_parser import parse_resume
        print(f"Parsing resume file: {args.resume}")
        structured = parse_resume(args.resume)
        target_data = structured.model_dump()
    else:
        prof_data = load_profile_data()
        target_data = prof_data.get("candidate", {}) if prof_data else {}

    if not target_data:
        print("No resume or candidate profile available to evaluate. Run `job-finder setup` first.")
        return

    if args.jd_file or args.jd_url:
        from job_finder import ats_view
        jd_text = ats_view.load_jd_text(jd_file=args.jd_file, jd_url=args.jd_url)
        if not jd_text.strip():
            ui.error("Could not read any job description text from the given source.")
            sys.exit(1)
        sys.exit(ats_view.render(ats_view.score_against_jd(target_data, jd_text), as_json=args.json))

    # The scorer prints progress lines; keep them off stdout so --json stays machine-readable
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
        ats_eval = evaluate_master_resume(target_data)
    if args.json and not args.optimize:
        ui.print_json(ats_eval)
        return
    ats_score = ats_eval.get("ats_score", 80)
    suggestions = ats_eval.get("suggestions", [])

    print("\n========================================================")
    print(f"           MASTER RESUME ATS HEALTH AUDIT: {ats_score}/100")
    print("========================================================")
    print(f"  • Skill Keywords  : {ats_eval.get('skills_count')} core taxonomy matches")
    print(f"  • Quantified Ratio: {ats_eval.get('quantified_percentage')}% of bullets contain metrics (%, £/$, numbers)")
    print(f"  • Estimated Tenure: {ats_eval.get('candidate_years')} years relevant experience")

    if suggestions:
        print("\nKey ATS Improvement Tips:")
        for tip in suggestions:
            print(f"  • {tip}")

    if args.optimize:
        from backend.services.gemini_client import generate_content_with_fallback
        prof_data = load_profile_data()
        cand = prof_data.get("candidate", {})
        cur_summary = cand.get("experience_summary", "")
        raw_skills = cand.get("core_skills", [])
        if isinstance(raw_skills, list):
            skills_str = ", ".join(str(s) for s in raw_skills[:12])
        elif isinstance(raw_skills, dict):
            skills_str = ", ".join(list(raw_skills.keys())[:12])
        else:
            skills_str = ""
        prompt = (
            "Optimize this professional summary for ATS conversion, keyword density, and executive impact.\n"
            "Keep it to 2-3 visual lines (~25-45 words).\n"
            "CRITICAL: Use ONLY keywords from the Core Skills and facts from the Current Summary below. Do not add skills, tools or numbers that are not stated there. Never invent metrics.\n"
            f"Candidate Name: {cand.get('name')}\n"
            f"Current Summary: {cur_summary}\n"
            f"Core Skills: {skills_str}\n"
            "Return ONLY the plain optimized summary text without any markdown commentary or quotes."
        )
        print("\nGenerating AI-Optimized Summary...")
        new_summary = generate_content_with_fallback(prompt)
        if new_summary:
            cand["experience_summary"] = new_summary.strip().strip('"')
            prof_data["candidate"] = cand
            save_profile_data(prof_data)
            print(f"Auto-Optimized Summary Saved:\n  \"{cand['experience_summary']}\"")
            
            # Re-evaluate ATS health score after optimization
            post_eval = evaluate_master_resume(cand)
            post_score = post_eval.get("ats_score", 80)
            print(f"Updated Master Resume ATS Health Score: {post_score}/100 ({post_eval.get('skills_count')} taxonomy keywords matched)\n")
