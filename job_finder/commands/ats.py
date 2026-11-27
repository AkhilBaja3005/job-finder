"""
`job-finder ats`: ATS checks.

    job-finder ats                     master-resume health audit (AI: what your target roles expect vs what you show)
    job-finder ats --add-skills        ... then add skills your profile evidences but doesn't list (asks first, backs up)
    job-finder ats --jd-url <url>      explain your fit for one job, requirement by requirement
    job-finder ats --keyword           use the old fixed-keyword engine instead of the AI analysis
"""

import argparse
import contextlib
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime

from job_finder import ui

logger = logging.getLogger(__name__)


def _run_audit(target_data: dict, prefs: dict, keyword: bool) -> dict:
    """AI audit, or the old keyword audit if forced / the LLM is unavailable (labelled in the result)."""
    from backend.services.ats_scorer import evaluate_master_resume
    note = None
    if not keyword:
        from backend.services.fit_scorer import FitUnavailable
        from backend.services.resume_audit import audit_master_resume
        try:
            with contextlib.redirect_stdout(sys.stderr):   # the LLM client prints progress lines
                return audit_master_resume(target_data, prefs)
        except FitUnavailable as e:
            note = f"AI audit unavailable ({e}); showing the old keyword audit instead."
    # The keyword scorer prints progress lines; keep them off stdout so --json stays clean
    with contextlib.redirect_stdout(sys.stderr):
        legacy = evaluate_master_resume(target_data)
    legacy["engine"] = "keyword"
    if note:
        legacy["note"] = note
    return legacy


def _print_audit(ev: dict) -> None:
    if ev.get("note"):
        ui.warn(ev["note"])
    score = ev.get("ats_score", 0)
    print("\n========================================================")
    if ev.get("engine") == "ai":
        print(f"      MASTER RESUME HEALTH: {score}/100   (AI audit)")
        print("========================================================")
        print(f"  • Target          : {ev.get('target_field') or '-'}  ({ev.get('targets')})")
        print(f"  • Skills coverage : {ev.get('skills_coverage')}%  -  {ev.get('skills_count')} of {ev.get('expected_total')} "
              f"skills these roles expect are in your Skills section")
        if ev.get("hidden_skills"):
            print("  • Shown but not listed (ATS skill filters can't see these):")
            for h in ev["hidden_skills"]:
                print(f"      + {h['skill']}" + (f"   <- {h['evidence']}" if h.get("evidence") else ""))
        if ev.get("other_evidenced_skills"):
            print(f"  • Also evidenced  : {', '.join(ev['other_evidenced_skills'])}")
        if ev.get("gaps"):
            print(f"  • Real gaps       : {', '.join(ev['gaps'])}  (no evidence in your profile; learn or build, don't just list)")
    else:
        print(f"      MASTER RESUME ATS HEALTH AUDIT: {score}/100   (keyword engine)")
        print("========================================================")
        print(f"  • Skill Keywords  : {ev.get('skills_count')} core taxonomy matches")
    print(f"  • Quantified      : {ev.get('quantified_percentage')}% of bullets contain metrics ({ev.get('quantified_bullets')}/{ev.get('total_bullets')})")
    print(f"  • Experience      : {ev.get('candidate_years')} years on the timeline")
    if ev.get("suggestions"):
        print("\nKey improvement tips:")
        for tip in ev["suggestions"]:
            print(f"  • {tip}")


def _add_skills(prof_data: dict, audit: dict, assume_yes: bool) -> None:
    """Append evidenced-but-unlisted skills to core_skills, after confirmation, with a timestamped backup."""
    from backend.job_finder_mcp.tools.profile_tools import _checked_save_path, save_profile_data
    from backend.services.resume_audit import skills_to_add

    cand = prof_data.get("candidate", {})
    if not isinstance(cand.get("core_skills"), list):
        ui.warn("core_skills in your profile isn't a simple list; add these by hand instead.")
        return
    new = skills_to_add(audit, cand)
    if not new:
        ui.info("Nothing to add: every skill your profile evidences is already listed.")
        return
    print(f"\nWill add to core_skills: {', '.join(new)}")
    print("(each is shown in your own experience/projects; real gaps are never added)")
    if not assume_yes:
        if not sys.stdin.isatty():
            ui.error("Not interactive: re-run with --yes to confirm.")
            sys.exit(2)
        if input("Add them? [y/N] ").strip().lower() not in ("y", "yes"):
            print("No changes made.")
            return
    path = _checked_save_path()
    backup = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    cand["core_skills"] = cand["core_skills"] + new
    prof_data["candidate"] = cand
    save_profile_data(prof_data)
    ui.info(f"Added {len(new)} skill(s). Backup: {backup}")


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data, save_profile_data

    target_data = None
    using_profile = True
    if args.resume and os.path.exists(args.resume):
        from backend.services.resume_parser import parse_resume
        print(f"Parsing resume file: {args.resume}")
        structured = parse_resume(args.resume)
        target_data = structured.model_dump()
        using_profile = False
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
        with contextlib.redirect_stdout(sys.stderr):       # keep LLM progress lines out of --json output
            result = ats_view.score_against_jd(target_data, jd_text, keyword=args.keyword)
        sys.exit(ats_view.render(result, as_json=args.json))

    prefs = (load_profile_data() or {}).get("search_preferences", {})
    ats_eval = _run_audit(target_data, prefs, args.keyword)
    if args.json and not args.optimize and not args.add_skills:
        ui.print_json(ats_eval)
        return
    _print_audit(ats_eval)

    if args.add_skills:
        if not using_profile or ats_eval.get("engine") != "ai":
            ui.warn("--add-skills needs the AI audit of your saved profile (not --resume / --keyword).")
        else:
            _add_skills(load_profile_data(), ats_eval, getattr(args, "yes", False))

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
            post = _run_audit(cand, prefs, args.keyword)
            print(f"Updated Master Resume Health Score: {post.get('ats_score')}/100\n")
