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
        help="View or inspect candidate profile configuration",
    )
    profile_parser.add_argument("--show", action="store_true", help="Display current candidate profile")

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
        result = asyncio.run(run_browser_use_autofill(args.url, auto_submit=args.submit, model_name=args.model))
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
        import json
        candidate_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "config", "candidate_profile.json")),
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


if __name__ == "__main__":
    main()
