"""Unified CLI dispatcher for Job Finder AI."""

import argparse
import sys
import os


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

    # 2. Apply subcommand
    apply_parser = subparsers.add_parser(
        "apply",
        help="Run ad-hoc browser auto-filler on a specific job application URL",
    )
    apply_parser.add_argument("url", type=str, help="Job posting URL")
    apply_parser.add_argument("--submit", action="store_true", help="Auto-submit the application if safe")
    apply_parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="LLM model to use")

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

    args, unknown = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "scan":
        if args.auto_apply:
            os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
        import asyncio
        from applications_tracker.scheduled_job_scanner import run_pipeline
        asyncio.run(run_pipeline(args.url))

    elif args.subcommand == "apply":
        import asyncio
        from applications_tracker.scheduled_job_scanner import run_browser_use_autofill
        from backend.mcp.tools.profile_tools import load_profile_data
        prof = load_profile_data() or {}
        cand = prof.get("candidate", {})
        result = asyncio.run(run_browser_use_autofill(args.url, resume_data=cand, auto_submit=args.submit, model_name=args.model))
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

        import json
        candidate_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "config", "candidate_profile.json")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "config", "candidate_profile.example.json")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "candidate_profile.json")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "candidate_profile.json")),
        ]
        found = False
        for path in candidate_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"Profile: {path}")
                    print(json.dumps(data, indent=2))
                found = True
                break
        if not found:
            print("Candidate profile configuration file not found.")

    elif args.subcommand == "setup":
        print("\n🚀 ========================================================")
        print("          JOB FINDER AI - QUICK SETUP WIZARD")
        print("========================================================\n")
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env_path = os.path.join(repo_root, ".env")
        example_env = os.path.join(repo_root, ".env.example")
        profile_path = os.path.join(repo_root, "backend", "config", "candidate_profile.json")
        example_profile = os.path.join(repo_root, "backend", "config", "candidate_profile.example.json")

        # 1. Initialize .env
        if not os.path.exists(env_path):
            if os.path.exists(example_env):
                import shutil
                shutil.copy2(example_env, env_path)
                print(f"📄 Initialized .env configuration from template: {env_path}")
            else:
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("# Job Finder AI Environment Configuration\nPORT=8000\nSCRAPER_CONCURRENCY=5\n")
                print(f"📄 Created initial .env configuration file: {env_path}")
        else:
            print(f"✓ Found existing .env at {env_path}")

        # Inject GEMINI_API_KEY if provided
        if args.api_key:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nGEMINI_API_KEY={args.api_key}\n")
            print("🔑 Configured GEMINI_API_KEY into .env")

        # 2. Initialize candidate_profile.json
        if not os.path.exists(profile_path) and os.path.exists(example_profile):
            import shutil
            os.makedirs(os.path.dirname(profile_path), exist_ok=True)
            shutil.copy2(example_profile, profile_path)
            print(f"👤 Initialized candidate_profile.json from template: {profile_path}")

        # 3. Resume sync if provided or present
        resume_target = args.resume
        if not resume_target:
            from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags
            resume_target = find_master_resume_with_mac_tags()

        if resume_target and os.path.exists(resume_target):
            print(f"📄 Syncing candidate profile from resume: {resume_target}")
            import asyncio
            from backend.mcp.tools.profile_tools import handle_sync_candidate_profile_from_resume
            res = asyncio.run(handle_sync_candidate_profile_from_resume({"resume_path": resume_target}))
            if res.get("success"):
                print(f"✅ Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
            else:
                print(f"ℹ️ Could not auto-parse resume: {res.get('error')}")
        else:
            print("ℹ️ Tip: Run `job-finder profile --sync /path/to/resume.pdf` anytime to import your full resume.")

        print("\n✅ Setup complete! You're ready to run:")
        print("   - `job-finder profile --show` : Review your parsed candidate profile")
        print("   - `job-finder scan`           : Run autonomous job search and ATS tailoring")
        print("   - `job-finder server`         : Start web dashboard on http://localhost:8000")
        print("   - `job-finder mcp`            : Run MCP server for Claude/Cursor IDE\n")


if __name__ == "__main__":
    main()
