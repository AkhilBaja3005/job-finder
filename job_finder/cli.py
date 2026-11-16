"""Unified CLI dispatcher for Job Finder AI."""

import argparse
import sys
import os
import json
import re
import logging

logger = logging.getLogger(__name__)

def load_workspace_env():
    """Loads .env configuration across candidate locations prior to command execution."""
    try:
        from dotenv import load_dotenv
        custom_root = os.environ.get("JOB_FINDER_ROOT")
        if custom_root:
            ws_env = os.path.join(custom_root, ".env")
            if os.path.exists(ws_env):
                load_dotenv(ws_env, override=True)
            return

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
    REPO_ROOT,
    os.path.join(REPO_ROOT, "backend"),
    os.path.join(REPO_ROOT, "site-packages", "backend"),
    os.path.dirname(os.path.abspath(__file__)),
]:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)


from job_finder.updates import check_for_updates, _parse_ver  # noqa: E402,F401


def main():
    """Console entry point: friendly errors, clean Ctrl-C, full traceback with --debug."""
    try:
        _main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        if "--debug" in sys.argv or os.getenv("JOB_FINDER_DEBUG"):
            raise
        from job_finder import ui
        ui.error(f"{type(exc).__name__}: {exc}")
        ui.error("Run again with --debug for the full traceback, or `job-finder doctor` to check your setup.")
        sys.exit(1)




def _main():
    from job_finder import __version__
    from job_finder.cli_parser import build_parser
    parser = build_parser(__version__)

    # Optional shell tab-completion: `pip install argcomplete` then `eval "$(register-python-argcomplete job-finder)"`
    try:
        import argcomplete  # type: ignore[import-not-found]
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    # Unknown flags are errors (typos used to be ignored silently)
    args = parser.parse_args()

    from job_finder import ui
    from job_finder.logging_setup import configure_logging
    ui.configure(quiet=args.quiet, no_color=args.no_color)
    configure_logging(verbose=args.verbose, quiet=args.quiet)

    if args.subcommand == "doctor":
        from job_finder.doctor import run_doctor
        load_workspace_env()
        sys.exit(run_doctor(as_json=args.json))


    if not args.subcommand:
        parser.print_help()
        check_for_updates()
        sys.exit(0)

    # Check for available package updates unless in quiet/mcp stdio mode
    if args.subcommand != "mcp":
        check_for_updates()

    if args.subcommand in ("scan", "apply") and getattr(args, "dry_run", False):
        # Dry run: fill and review only. Overrides .env and any auto-submit flag so nothing is submitted.
        os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "0"
        os.environ["BROWSER_USE_DISABLE_GUARDRAILS"] = "0"
        args.auto_apply = False
        if hasattr(args, "submit"):
            args.submit = False
        ui.info("Dry run: applications will be filled but never submitted.")

    if args.subcommand == "scan":
        from job_finder.commands.scan import run as _run
        _run(args)

    elif args.subcommand == "apply":
        from job_finder.commands.apply import run as _run
        _run(args)

    elif args.subcommand == "server":
        os.environ["PORT"] = str(args.port)
        os.environ["HOST"] = args.host
        from backend.main import start_server
        start_server()

    elif args.subcommand == "mcp":
        from backend.job_finder_mcp.server import main as mcp_main
        mcp_main()

    elif args.subcommand == "profile":
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

    elif args.subcommand == "status":
        from job_finder.commands_extra import run_status
        sys.exit(run_status(as_json=args.json))

    elif args.subcommand == "config":
        from job_finder.commands_extra import run_config
        sys.exit(run_config(as_json=args.json))

    elif args.subcommand == "export":
        from backend.services.application_tracker import list_applications
        from job_finder.commands_extra import export_applications
        sys.exit(export_applications(list_applications(), args.out, fmt=args.format, status=args.status))

    elif args.subcommand == "cover-letter":
        from job_finder.commands_extra import run_cover_letter
        sys.exit(run_cover_letter(args.title, args.company, args.jd_file, args.jd_url, args.out, as_json=args.json))

    elif args.subcommand == "ats":
        from job_finder.commands.ats import run as _run
        _run(args)

    elif args.subcommand == "tracker":
        from backend.services.application_tracker import list_applications
        from job_finder.tracker_view import render_tracker
        sys.exit(render_tracker(list_applications(), status=args.status, limit=args.limit, as_json=args.json))

    elif args.subcommand == "company":
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

    elif args.subcommand == "interview":
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


    elif args.subcommand == "targetjobs":
        from job_finder.commands.targetjobs import run as _run
        _run(args)

    elif args.subcommand == "jobserve":
        from job_finder.commands.jobserve import run as _run
        _run(args)

    elif args.subcommand == "follow-up":
        from job_finder.commands.follow_up import run as _run
        _run(args)

    elif args.subcommand == "harvest-slugs":
        import asyncio
        from backend.services.company_slug_harvester import harvest_all_company_slugs
        from backend.services.company_slug_registry import validate_all_unverified_slugs, get_active_slugs

        sources = [s.strip().lower() for s in args.source.split(",")]
        asyncio.run(harvest_all_company_slugs(sources=sources))

        if args.validate:
            asyncio.run(validate_all_unverified_slugs(ats_filter=args.ats, limit=args.limit))

        active = get_active_slugs(ats=args.ats)
        print("\nActive Company Board Registry Summary:")
        for platform, slugs in active.items():
            print(f"  • {platform.capitalize():<12}: {len(slugs)} active board slugs")

    elif args.subcommand == "sponsor":
        from job_finder.commands.sponsor import run as _run
        _run(args)

    elif args.subcommand == "setup":
        from job_finder.commands.setup import run as _run
        _run(args)



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
