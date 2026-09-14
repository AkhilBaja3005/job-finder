"""Unified CLI dispatcher for Job Finder AI."""

import argparse
import sys
import os
import json

def load_workspace_env():
    """Loads .env configuration across all candidate locations prior to command execution."""
    try:
        from dotenv import load_dotenv
        env_candidates = [
            os.path.join(os.getcwd(), ".env"),
            os.path.expanduser("~/.config/job-finder/.env"),
            os.path.expanduser("~/.job-finder/.env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        ]
        for env_path in env_candidates:
            if os.path.exists(env_path):
                load_dotenv(env_path, override=True)
        load_dotenv(override=True)
    except Exception:
        pass

# Immediately load environment variables
load_workspace_env()

# Ensure backend root is always on sys.path for CLI execution across repo and installed wheel
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for candidate in [
    os.path.join(REPO_ROOT, "backend"),
    os.path.join(REPO_ROOT, "site-packages", "backend"),
    os.path.dirname(os.path.abspath(__file__)),
]:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)


def main():
    parser = argparse.ArgumentParser(
        prog="job-finder",
        description="Job Finder AI - Autonomous Agentic Career & Application Toolkit",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. Scanner subcommand
    scanner_parser = subparsers.add_parser(
        "scan",
        help="Run the automated job discovery, filtering, and resume tailoring pipeline",
    )
    scanner_parser.add_argument("url", nargs="?", default=None, help="Target specific job URL to process directly (optional)")
    scanner_parser.add_argument("--auto-apply", action="store_true", help="Enable automatic browser form submission")
    scanner_parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")
    scanner_parser.add_argument("--tailor-timeout", type=float, default=90.0, help="Resume tailoring timeout in seconds (default: 90s)")
    scanner_parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps per application (default: 50)")
    scanner_parser.add_argument("--limit", type=int, default=0, help="Max applications to process (default: 0 = unlimited)")
    scanner_parser.add_argument("--min-ats", type=int, default=None, help="Minimum ATS score threshold (default: from profile)")
    scanner_parser.add_argument("--role", type=str, default=None, help="Target role filter override")
    scanner_parser.add_argument("--location", type=str, default=None, help="Target location filter override")
    scanner_parser.add_argument("--timeframe", type=str, default=None, help="Search freshness window (e.g. 24h, 48h, 1w)")
    scanner_parser.add_argument("--model", type=str, default=None, help="Gemini LLM model override")
    scanner_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    scanner_parser.add_argument("--top-applicant", action="store_true", help="Scan LinkedIn specifically for Top Applicant postings and apply directly without JD scoring")

    # 2. Apply subcommand
    apply_parser = subparsers.add_parser(
        "apply",
        help="Run ad-hoc browser auto-filler on a specific job application URL",
    )
    apply_parser.add_argument("url", type=str, help="Job posting URL")
    apply_parser.add_argument("--submit", action="store_true", help="Auto-submit the application if safe")
    apply_parser.add_argument("--timeout", type=float, default=300.0, help="Application timeout in seconds (default: 300s)")
    apply_parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps (default: 50)")
    apply_parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="LLM model to use (default: gemini-3.5-flash-lite)")
    apply_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    apply_parser.add_argument("--resume", type=str, default=None, help="Path to resume PDF to upload (default: auto-detected master resume)")

    # 3. Server subcommand
    server_parser = subparsers.add_parser(
        "server",
        help="Start the FastAPI backend server and dashboard",
    )
    server_parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    server_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address (default: 0.0.0.0)")

    # 4. MCP subcommand
    subparsers.add_parser(
        "mcp",
        help="Start the Model Context Protocol (MCP) server for IDEs and AI agents",
    )

    # 5. Profile subcommand
    profile_parser = subparsers.add_parser(
        "profile",
        help="View, inspect, or auto-sync candidate profile configuration from resume",
    )
    profile_parser.add_argument("--show", action="store_true", help="Display current candidate profile")
    profile_parser.add_argument("--sync", nargs="?", const="AUTO", default=None, help="Parse and sync profile from a resume file (default: auto-detect master resume)")

    # 6. Setup subcommand
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive guided wizard to initialize candidate profile, environment, and master resume",
    )
    setup_parser.add_argument("--resume", type=str, default=None, help="Optional initial resume file to parse (PDF/DOCX/LaTeX)")
    setup_parser.add_argument("--api-key", type=str, default=None, help="Gemini API Key")

    # 7. Status subcommand
    subparsers.add_parser(
        "status",
        help="Display system configuration, environment status, master resume, and API keys",
    )

    # 8. ATS subcommand
    ats_parser = subparsers.add_parser(
        "ats",
        help="Run standalone ATS Health Audit on your candidate profile or master resume",
    )
    ats_parser.add_argument("--resume", type=str, default=None, help="Path to resume file to evaluate (default: active candidate profile)")
    ats_parser.add_argument("--optimize", action="store_true", help="Auto-optimize summary for ATS conversion using AI")

    # 9. Tracker subcommand
    tracker_parser = subparsers.add_parser(
        "tracker",
        help="List and inspect tracked applications, saved roles, and tailored resumes",
    )
    tracker_parser.add_argument("--status", type=str, default="all", help="Filter by status (all, saved, tailored, applied)")
    tracker_parser.add_argument("--limit", type=int, default=20, help="Max entries to list (default: 20)")

    args, unknown = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "scan":
        if args.auto_apply:
            os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
        import asyncio
        from applications_tracker.scheduled_job_scanner import run_pipeline
        asyncio.run(run_pipeline(
            target_url=args.url,
            timeout=args.timeout,
            tailor_timeout=args.tailor_timeout,
            max_steps=args.max_steps,
            max_apps=args.limit if args.limit > 0 else None,
            min_ats=args.min_ats,
            role=args.role,
            location_override=args.location,
            timeframe_override=args.timeframe,
            model_override=args.model,
            headless=True if args.headless else None,
            auto_submit_override=True if args.auto_apply else None,
            top_applicant_only=True if args.top_applicant else None
        ))

    elif args.subcommand == "apply":
        import asyncio
        from applications_tracker.scheduled_job_scanner import run_browser_use_autofill, find_master_resume_with_mac_tags
        from backend.mcp.tools.profile_tools import load_profile_data
        prof = load_profile_data() or {}
        cand = prof.get("candidate", {})
        target_resume = args.resume or find_master_resume_with_mac_tags()
        result = asyncio.run(asyncio.wait_for(
            run_browser_use_autofill(
                args.url,
                resume_data=cand,
                resume_pdf_path=target_resume,
                auto_submit=args.submit,
                model_name=args.model,
                headless=args.headless,
                max_steps=args.max_steps
            ),
            timeout=args.timeout
        ))
        print(f"[Result] {result}")

    elif args.subcommand == "server":
        os.environ["PORT"] = str(args.port)
        os.environ["HOST"] = args.host
        from backend.main import start_server
        start_server()

    elif args.subcommand == "mcp":
        from backend.mcp.server import main as mcp_main
        mcp_main()

    elif args.subcommand == "profile":
        if getattr(args, "sync", None):
            import asyncio
            from backend.mcp.tools.profile_tools import handle_sync_candidate_profile_from_resume
            resume_arg = None if args.sync == "AUTO" else args.sync
            res = asyncio.run(handle_sync_candidate_profile_from_resume({"resume_path": resume_arg}))
            if res.get("success"):
                print(f"✅ {res.get('message')}")
                print(f"📊 Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
            else:
                print(f"❌ Sync failed: {res.get('error')}")
            return

        from backend.mcp.tools.profile_tools import get_profile_config_path, load_profile_data
        prof_path = get_profile_config_path()
        data = load_profile_data()
        if data:
            print(f"Profile: {prof_path}")
            print(json.dumps(data, indent=2))
        else:
            print(f"Candidate profile not found. Run `job-finder setup` to initialize one at: {prof_path}")

    elif args.subcommand == "status":
        from backend.mcp.tools.profile_tools import load_profile_data, get_profile_config_path
        from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags

        print("\n🔍 ========================================================")
        print("        JOB FINDER AI SYSTEM HEALTH & STATUS")
        print("========================================================")
        g_key = os.getenv("GEMINI_API_KEY")
        masked_key = f"{g_key[:4]}...{g_key[-4:]}" if (g_key and len(g_key) > 8) else ("Configured ✅" if g_key else "Missing ❌")
        print(f"  • Gemini API Key    : {masked_key}")

        master_resume = find_master_resume_with_mac_tags()
        resume_status = f"{master_resume} (Exists ✅)" if (master_resume and os.path.exists(master_resume)) else "Not set (Run `job-finder setup`)"
        print(f"  • Master Resume     : {resume_status}")

        prof_path = get_profile_config_path()
        data = load_profile_data()
        if data and "candidate" in data:
            cand = data["candidate"]
            prefs = data.get("search_preferences", {})
            print(f"  • Candidate Name    : {cand.get('name', 'N/A')}")
            print(f"  • Base Location     : {cand.get('location', 'N/A')}")
            print(f"  • Target Roles      : {', '.join(prefs.get('target_roles', [])) or 'N/A'}")
            print(f"  • Target Locations  : {', '.join(prefs.get('target_locations', [])) or 'N/A'}")
            print(f"  • ATS Score Floor   : {prefs.get('min_ats_score_threshold', 65)}%")
        else:
            print(f"  • Candidate Profile : Not configured ({prof_path})")
        print("========================================================\n")

    elif args.subcommand == "ats":
        from backend.mcp.tools.profile_tools import load_profile_data, save_profile_data
        from backend.services.ats_scorer import evaluate_master_resume

        target_data = None
        if args.resume and os.path.exists(args.resume):
            from backend.services.resume_parser import parse_resume
            print(f"📄 Parsing resume file: {args.resume}")
            structured = parse_resume(args.resume)
            target_data = structured.model_dump()
        else:
            prof_data = load_profile_data()
            target_data = prof_data.get("candidate", {}) if prof_data else {}

        if not target_data:
            print("❌ No resume or candidate profile available to evaluate. Run `job-finder setup` first.")
            return

        ats_eval = evaluate_master_resume(target_data)
        ats_score = ats_eval.get("ats_score", 80)
        suggestions = ats_eval.get("suggestions", [])

        print("\n📊 ========================================================")
        print(f"           MASTER RESUME ATS HEALTH AUDIT: {ats_score}/100")
        print("========================================================")
        print(f"  • Skill Keywords  : {ats_eval.get('skills_count')} core taxonomy matches")
        print(f"  • Quantified Ratio: {ats_eval.get('quantified_percentage')}% of bullets contain metrics (%, £/$, numbers)")
        print(f"  • Estimated Tenure: {ats_eval.get('candidate_years')} years relevant experience")

        if suggestions:
            print("\n💡 Key ATS Improvement Tips:")
            for tip in suggestions:
                print(f"  • {tip}")

        if args.optimize:
            from backend.services.gemini_client import generate_content_with_fallback
            prof_data = load_profile_data()
            cand = prof_data.get("candidate", {})
            cur_summary = cand.get("experience_summary", "")
            skills_str = ", ".join(list(cand.get("core_skills", {}).keys())[:10]) if isinstance(cand.get("core_skills"), dict) else ""
            prompt = (
                "Optimize this professional summary for ATS conversion and executive impact.\n"
                "Keep it to 2-3 visual lines (~25-45 words). Focus on quantified achievements and core skills.\n"
                f"Candidate Name: {cand.get('name')}\n"
                f"Current Summary: {cur_summary}\n"
                f"Core Skills: {skills_str}\n"
                "Return ONLY the plain optimized summary text without any markdown commentary or quotes."
            )
            print("\n✨ Generating AI-Optimized Summary...")
            new_summary = generate_content_with_fallback(prompt)
            if new_summary:
                cand["experience_summary"] = new_summary.strip().strip('"')
                prof_data["candidate"] = cand
                save_profile_data(prof_data)
                print(f"✅ Auto-Optimized Summary Saved:\n  \"{cand['experience_summary']}\"\n")

    elif args.subcommand == "tracker":
        from backend.services.application_tracker import list_applications
        apps = list_applications()
        if not apps:
            print("ℹ️ No tracked job applications found.")
            return

        status_filter = args.status.lower()
        if status_filter != "all":
            apps = [a for a in apps if a.get("status", "").lower() == status_filter]

        apps = apps[:args.limit]
        print(f"\n📋 Tracker Pipeline ({len(apps)} entries):")
        print(f"{'STATUS':<12} {'ATS':<6} {'COMPANY':<20} {'ROLE':<25} {'DATE':<12}")
        print("-" * 78)
        for a in apps:
            st = a.get("status", "saved")[:11]
            sc = f"{a.get('score', 'N/A')}%"
            co = (a.get("company") or "Unknown")[:19]
            ro = (a.get("job_title") or "Position")[:24]
            dt = str(a.get("updated_at") or a.get("created_at") or "")[:10]
            print(f"{st:<12} {sc:<6} {co:<20} {ro:<25} {dt:<12}")
        print("-" * 78 + "\n")


    elif args.subcommand == "setup":
        print("\n🚀 ========================================================")
        print("          JOB FINDER AI - QUICK SETUP WIZARD")
        print("========================================================\n")
        from config.constants import resolve_workspace_root
        from backend.mcp.tools.profile_tools import get_profile_config_path, get_profile_save_path

        ws = resolve_workspace_root()
        env_path = os.path.join(ws, ".env")
        
        # Look for template .env.example
        pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        example_env_candidates = [
            os.path.join(ws, ".env.example"),
            os.path.join(pkg_root, ".env.example"),
            os.path.join(pkg_root, "backend", ".env.example"),
        ]
        example_env = next((p for p in example_env_candidates if os.path.exists(p)), None)

        profile_path = get_profile_save_path()
        example_profile_candidates = [
            os.path.join(pkg_root, "backend", "config", "candidate_profile.example.json"),
            os.path.join(pkg_root, "config", "candidate_profile.example.json"),
            os.path.join(ws, "backend", "config", "candidate_profile.example.json"),
        ]
        example_profile = next((p for p in example_profile_candidates if os.path.exists(p)), None)

        # 1. Initialize .env in workspace root
        os.makedirs(os.path.dirname(env_path), exist_ok=True)
        if not os.path.exists(env_path):
            if example_env and os.path.exists(example_env):
                import shutil
                shutil.copy2(example_env, env_path)
                print(f"📄 Initialized .env configuration from template: {env_path}")
            else:
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("# Job Finder AI Environment Configuration\nPORT=8000\nSCRAPER_CONCURRENCY=5\n")
                print(f"📄 Created initial .env configuration file: {env_path}")

        else:
            print(f"✓ Found existing .env at {env_path}")

        # Configure GEMINI_API_KEY
        existing_key = os.getenv("GEMINI_API_KEY")
        if args.api_key:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nGEMINI_API_KEY={args.api_key}\n")
            os.environ["GEMINI_API_KEY"] = args.api_key
            print("🔑 Configured GEMINI_API_KEY into .env")
        elif not existing_key:
            if sys.stdin.isatty():
                print("\n🔑 Gemini API Key is required for resume parsing, ATS scoring & browser automation.")
                print("   (Get a free key at https://aistudio.google.com/)")
                try:
                    user_key = input("  Enter your GEMINI_API_KEY: ").strip()
                    if user_key:
                        with open(env_path, "a", encoding="utf-8") as f:
                            f.write(f"\nGEMINI_API_KEY={user_key}\n")
                        os.environ["GEMINI_API_KEY"] = user_key
                        print("✅ GEMINI_API_KEY saved to .env")
                except (EOFError, KeyboardInterrupt):
                    print("\nSkipping API key prompt.")
            else:
                print("⚠️  GEMINI_API_KEY is not set in environment or .env. You can pass it via `job-finder setup --api-key <KEY>`")
        else:
            masked = existing_key[:4] + "..." + existing_key[-4:] if len(existing_key) > 8 else "***"
            print(f"🔑 Gemini API Key configured ({masked})")

        # Configure SMTP Notifications (Optional)
        existing_smtp_user = os.getenv("SMTP_USER")
        if sys.stdin.isatty():
            if not existing_smtp_user:
                print("\n📧 Email Notifications for Applied & Review Alerts (Optional)")
                try:
                    enable_smtp = input("  Would you like to configure email alerts for submitted & failed jobs? (y/N): ").strip().lower()
                    if enable_smtp in ("y", "yes"):
                        smtp_user = input("  Enter your SMTP email address (e.g. yourname@gmail.com): ").strip()
                        if smtp_user:
                            smtp_pass = input("  Enter your SMTP App Password: ").strip()
                            # Update .env
                            with open(env_path, "r", encoding="utf-8") as ef:
                                lines = ef.readlines()
                            new_lines = []
                            for line in lines:
                                if line.startswith("SMTP_USER="):
                                    new_lines.append(f"SMTP_USER={smtp_user}\n")
                                elif line.startswith("SMTP_PASSWORD="):
                                    new_lines.append(f"SMTP_PASSWORD={smtp_pass}\n")
                                elif line.startswith("EMAIL_FROM="):
                                    new_lines.append(f"EMAIL_FROM={smtp_user}\n")
                                else:
                                    new_lines.append(line)
                            with open(env_path, "w", encoding="utf-8") as ef:
                                ef.writelines(new_lines)
                            os.environ["SMTP_USER"] = smtp_user
                            os.environ["SMTP_PASSWORD"] = smtp_pass
                            os.environ["EMAIL_FROM"] = smtp_user
                            print("✅ SMTP email notifications configured in .env")
                except (EOFError, KeyboardInterrupt):
                    print("\nSkipping email configuration.")

        # 2. Initialize candidate_profile.json in workspace root
        if not os.path.exists(profile_path) and example_profile and os.path.exists(example_profile):
            import shutil
            os.makedirs(os.path.dirname(profile_path), exist_ok=True)
            shutil.copy2(example_profile, profile_path)
            print(f"👤 Initialized candidate_profile.json in workspace: {profile_path}")
        elif os.path.exists(profile_path):
            print(f"✓ Found existing candidate profile at: {profile_path}")


        # 3. Master Resume Path Configuration & Profile Sync
        existing_master = os.getenv("MASTER_RESUME_PATH")
        resume_target = args.resume

        if resume_target:
            resume_target = os.path.abspath(os.path.expanduser(resume_target.strip('\'"')))
        elif sys.stdin.isatty():
            print("\n📄 ========================================================")
            print("             MASTER RESUME CONFIGURATION")
            print("========================================================")
            detected_resume = existing_master
            if not detected_resume or not os.path.exists(detected_resume):
                from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags
                detected_resume = find_master_resume_with_mac_tags()

            default_hint = f" [{detected_resume}]" if (detected_resume and os.path.exists(detected_resume)) else ""
            print("  Please provide the path to your Master Resume (PDF/DOCX).")
            print("  This will be saved as MASTER_RESUME_PATH in .env and used for all job applications.")
            try:
                user_resume = input(f"  Enter Master Resume path{default_hint}: ").strip().strip('\'"')
                if user_resume:
                    resume_target = os.path.abspath(os.path.expanduser(user_resume))
                elif detected_resume and os.path.exists(detected_resume):
                    resume_target = detected_resume
            except (EOFError, KeyboardInterrupt):
                print("\nSkipping resume path prompt.")
                if detected_resume and os.path.exists(detected_resume):
                    resume_target = detected_resume
        else:
            if existing_master and os.path.exists(existing_master):
                resume_target = existing_master
            else:
                from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags
                resume_target = find_master_resume_with_mac_tags()

        if resume_target and os.path.exists(resume_target):
            # Save or update MASTER_RESUME_PATH in .env
            try:
                with open(env_path, "r", encoding="utf-8") as ef:
                    lines = ef.readlines()
                new_lines = []
                found_master = False
                for line in lines:
                    if line.startswith("MASTER_RESUME_PATH="):
                        new_lines.append(f"MASTER_RESUME_PATH={resume_target}\n")
                        found_master = True
                    else:
                        new_lines.append(line)
                if not found_master:
                    new_lines.append(f"\nMASTER_RESUME_PATH={resume_target}\n")
                with open(env_path, "w", encoding="utf-8") as ef:
                    ef.writelines(new_lines)
                os.environ["MASTER_RESUME_PATH"] = resume_target
                print(f"✅ Saved MASTER_RESUME_PATH in .env: {resume_target}")
            except Exception as env_err:
                print(f"⚠️ Could not write MASTER_RESUME_PATH to .env: {env_err}")

            print(f"📄 Syncing candidate profile from resume: {resume_target}")
            import asyncio
            from backend.mcp.tools.profile_tools import handle_sync_candidate_profile_from_resume
            res = asyncio.run(handle_sync_candidate_profile_from_resume({"resume_path": resume_target}))
            if res.get("success"):
                print(f"✅ Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
                
                # Run ATS Health Audit & Display Improvement Tips
                try:
                    from backend.services.ats_scorer import evaluate_master_resume
                    from backend.mcp.tools.profile_tools import load_profile_data, save_profile_data
                    profile_data = load_profile_data()
                    ats_eval = evaluate_master_resume(profile_data.get("candidate", {}))
                    ats_score = ats_eval.get("ats_score", 80)
                    suggestions = ats_eval.get("suggestions", [])

                    print("\n📊 ========================================================")
                    print(f"           MASTER RESUME ATS HEALTH SCORE: {ats_score}/100")
                    print("========================================================")
                    print(f"  • Skill Keywords  : {ats_eval.get('skills_count')} core taxonomy matches")
                    print(f"  • Quantified Ratio: {ats_eval.get('quantified_percentage')}% of bullets contain metrics (%, £/$, numbers)")
                    print(f"  • Estimated Tenure: {ats_eval.get('candidate_years')} years relevant experience")

                    if suggestions:
                        print("\n💡 Key ATS Improvement Tips:")
                        for tip in suggestions:
                            print(f"  • {tip}")

                    # Interactive prompt to auto-enhance summary if suggestions exist
                    if sys.stdin.isatty() and suggestions:
                        try:
                            print("\n✨ Would you like AI to auto-optimize your summary to improve ATS conversion? [Y/n]: ", end="")
                            opt_choice = input().strip().lower()
                            if opt_choice in ("y", "yes", ""):
                                from backend.services.gemini_client import generate_content_with_fallback
                                cand = profile_data.get("candidate", {})
                                cur_summary = cand.get("experience_summary", "")
                                skills_str = ", ".join(list(cand.get("core_skills", {}).keys())[:10]) if isinstance(cand.get("core_skills"), dict) else ""
                                prompt = (
                                    "Optimize this professional summary for ATS conversion and executive impact.\n"
                                    "Keep it to 2-3 visual lines (~25-45 words). Focus on quantified achievements and core skills.\n"
                                    f"Candidate Name: {cand.get('name')}\n"
                                    f"Current Summary: {cur_summary}\n"
                                    f"Core Skills: {skills_str}\n"
                                    "Return ONLY the plain optimized summary text without any markdown commentary or quotes."
                                )
                                new_summary = generate_content_with_fallback(prompt)
                                if new_summary:
                                    cand["experience_summary"] = new_summary.strip().strip('"')
                                    profile_data["candidate"] = cand
                                    save_profile_data(profile_data)
                                    print(f"\n✅ Auto-Optimized Summary Saved:\n  \"{cand['experience_summary']}\"")
                        except (EOFError, KeyboardInterrupt):
                            print("\nSkipping summary optimization.")
                except Exception as ats_err:
                    print(f"ℹ️ Could not compute ATS baseline: {ats_err}")
            else:
                print(f"ℹ️ Could not auto-parse resume: {res.get('error')}")
        elif resume_target and not os.path.exists(resume_target):
            print(f"⚠️ Provided resume file does not exist: {resume_target}")
            print("ℹ️ Tip: Run `job-finder profile --sync /path/to/resume.pdf` anytime to import your full resume.")
        else:
            print("ℹ️ Tip: Run `job-finder profile --sync /path/to/resume.pdf` anytime to import your full resume.")

        # 4. Review Candidate Profile Completeness (Demographics, Location, Portals Password)
        profile_to_check = profile_path if (profile_path and os.path.exists(profile_path)) else example_profile
        if profile_to_check and os.path.exists(profile_to_check):
            try:
                with open(profile_to_check, "r", encoding="utf-8") as f:

                    prof_data = json.load(f)
                cand = prof_data.get("candidate", {})

                field_specs = [
                    ("name", "Full Name", "Candidate Name"),
                    ("email", "Email Address", "candidate@example.com"),
                    ("phone", "Phone Number", "+44 7123 456789"),
                    ("location", "Current Location", "London, UK"),
                    ("postal_code", "Postal Code / Postcode", "EC1A 1BB"),
                    ("gender", "Gender", "Male / Female / Non-binary / Prefer not to say"),
                    ("ethnicity", "Race / Ethnicity", "Asian / White / Black / Hispanic / Two or more"),
                    ("citizenship", "Citizenship / Nationality", "e.g. British / Indian / American"),
                    ("work_authorization", "Work Authorization", "e.g. Authorized to work in the UK"),
                    ("requires_sponsorship", "Requires Visa Sponsorship (True/False)", "False"),
                    ("portals_password", "Portals / Job Board Password (for auto-signup)", "Optional (Leave blank to use Google OAuth)")
                ]

                # Categorize which fields were parsed from resume vs populated from template defaults
                unfilled_fields = []
                default_derived_fields = []
                for key, label, placeholder in field_specs:
                    val = cand.get(key)
                    if val is None or val == "" or (isinstance(val, str) and (val.strip() == "" or val in ["Jane Doe", "jane.doe@example.com", "EC1A 1BB"])):
                        unfilled_fields.append((key, label, val if val is not None else ""))
                    elif key in ("gender", "ethnicity", "citizenship", "work_authorization", "requires_sponsorship", "postal_code"):
                        # Fields typically not on a standard resume, merged from defaults
                        default_derived_fields.append((key, label, str(val)))

                print("\n📋 ========================================================")
                print("     CANDIDATE PROFILE DATA PROVENANCE & REVIEW")
                print("========================================================")
                print("  📄 From Resume : Name, Contact Info, Work Experience, Education & Skills")
                print("  ⚙️ From Template: Demographic & compliance fields not present on standard resumes")
                if default_derived_fields:
                    print("\n  The following fields were initialized from defaults. Please verify them:")
                    for k, lbl, cur in default_derived_fields:
                        print(f"    • {lbl} ({k}): {cur}")

                if unfilled_fields:
                    print("\n⚠️  The following fields are EMPTY or PLACEHOLDERS and require your input:")
                    for k, lbl, _ in unfilled_fields:
                        print(f"    • {lbl} ({k})")

                # If interactive terminal session, prompt user to review or update
                fields_to_prompt = unfilled_fields + default_derived_fields
                if sys.stdin.isatty():
                    print("\n📝 Would you like to review or update any of these fields now?")
                    print("   (Press Enter to keep current value, or type new value to update):")
                    updated = False
                    for key, label, cur_val in fields_to_prompt:
                        default_hint = f" [{cur_val}]" if cur_val else ""
                        try:
                            user_input = input(f"  Enter {label}{default_hint}: ").strip()
                            if user_input:
                                if key == "requires_sponsorship":
                                    cand[key] = user_input.lower() in ("true", "1", "yes", "y")
                                else:
                                    cand[key] = user_input
                                updated = True
                        except (EOFError, KeyboardInterrupt):
                            print("\nSkipping remaining prompts.")
                            break

                    if updated:
                        prof_data["candidate"] = cand
                        with open(profile_path, "w", encoding="utf-8") as f:
                            json.dump(prof_data, f, indent=2)
                        print(f"\n✅ Updated candidate profile saved to: {profile_path}")
                else:
                    print(f"\n💡 Note: Review or edit these anytime in `{profile_path}` or run `job-finder profile`.")
            except Exception as pe:
                print(f"ℹ️ Could not inspect candidate profile: {pe}")

        print("\n✅ Setup complete! You're ready to run:")
        print("   - `job-finder profile --show` : Review your parsed candidate profile")
        print("   - `job-finder scan`           : Run autonomous job search and ATS tailoring")
        print("   - `job-finder server`         : Start web dashboard on http://localhost:8000")
        print("   - `job-finder mcp`            : Run MCP server for Claude/Cursor IDE\n")


def scanner_cli():
    """Direct entrypoint for job-finder-scanner with support for clean --help before loading dependencies."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="job-finder-scanner",
        description="Autonomous Scheduled Job Discovery & Application Pipeline",
    )
    parser.add_argument("url", nargs="?", default=None, help="Target specific job URL to process directly (optional)")
    parser.add_argument("--auto-apply", action="store_true", help="Enable automatic browser form submission")
    parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")
    parser.add_argument("--tailor-timeout", type=float, default=90.0, help="Resume tailoring timeout in seconds (default: 90s)")
    parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps per application (default: 50)")
    parser.add_argument("--limit", type=int, default=0, help="Max applications to process per run (default: 0 = unlimited)")
    parser.add_argument("--min-ats", type=int, default=None, help="Minimum ATS compatibility score threshold (default: from profile)")
    parser.add_argument("--role", type=str, default=None, help="Target role override")
    parser.add_argument("--location", type=str, default=None, help="Target location override")
    parser.add_argument("--timeframe", type=str, default=None, help="Search freshness window override (e.g. 24h, 48h, 1w)")
    parser.add_argument("--model", type=str, default=None, help="Gemini LLM model override for browser-use")
    parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    parser.add_argument("--top-applicant", action="store_true", help="Scan LinkedIn specifically for Top Applicant postings and apply directly without JD scoring")
    args = parser.parse_args()

    if args.auto_apply:
        os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"

    import asyncio
    from applications_tracker.scheduled_job_scanner import run_pipeline
    asyncio.run(run_pipeline(
        target_url=args.url,
        timeout=args.timeout,
        tailor_timeout=args.tailor_timeout,
        max_steps=args.max_steps,
        max_apps=args.limit if args.limit > 0 else None,
        min_ats=args.min_ats,
        role=args.role,
        location_override=args.location,
        timeframe_override=args.timeframe,
        model_override=args.model,
        headless=True if args.headless else None,
        auto_submit_override=True if args.auto_apply else None,
        top_applicant_only=True if args.top_applicant else None
    ))


if __name__ == "__main__":
    main()
