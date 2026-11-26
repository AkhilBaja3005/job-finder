"""Argument parser for the Job Finder CLI (kept separate from the command handlers in cli.py)."""

import argparse

EXAMPLES = """\
examples:
  job-finder setup                       first-time setup (resume, keys, browser login)
  job-finder doctor                      check keys, Chrome, CDP port and email config
  job-finder scan --limit 5              discover, score and prepare 5 applications
  job-finder scan --auto-apply --limit 3 submit applications (guardrails off, be sure)
  job-finder status                      configuration and master resume overview
  job-finder tracker --status blocked    applications waiting on a CAPTCHA or login
  job-finder tracker --json | jq .summary machine-readable output
  job-finder ats --jd-url <url>          score your resume against one job, with skill breakdown
  job-finder cover-letter "AI Engineer" Acme --jd-url <url> --out letter.txt
  job-finder export apps.csv --status applied   export tracked applications

environment:
  NO_COLOR=1                  disable colors      JOB_FINDER_NO_UPDATE_CHECK=1  skip update check
  JOB_FINDER_DEBUG=1          show tracebacks     JOB_FINDER_LOG_DIR=<dir>      where logs are written
"""


def build_parser(version: str) -> argparse.ArgumentParser:
    """Build the full `job-finder` parser with every subcommand."""
    parser = argparse.ArgumentParser(
        prog="job-finder",
        description="Job Finder AI - Autonomous Agentic Career & Application Toolkit",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print errors and requested data")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress (debug logging)")
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on errors")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output (also honors NO_COLOR)")
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {version}",
        help="Show program's version number and exit"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 1. Scanner subcommand
    scanner_parser = subparsers.add_parser(
        "scan",
        help="Run the automated job discovery, filtering, and resume tailoring pipeline",
    )
    scanner_parser.add_argument("url", nargs="?", default=None, help="Target specific job URL to process directly (optional)")
    scanner_parser.add_argument("--auto-apply", "--auto-submit", dest="auto_apply", action="store_true", help="Enable automatic browser form submission")
    scanner_parser.add_argument("--dry-run", action="store_true", help="Fill forms and stop at the review step; never submit (overrides --auto-apply and .env)")
    scanner_parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")
    scanner_parser.add_argument("--tailor-timeout", type=float, default=90.0, help="Resume tailoring timeout in seconds (default: 90s)")
    scanner_parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps per application (default: 50)")
    scanner_parser.add_argument("--limit", type=int, default=0, help="Max applications to process (default: 0 = unlimited)")
    scanner_parser.add_argument("--min-ats", type=int, default=None, help="Minimum ATS score threshold (default: from profile)")
    scanner_parser.add_argument("--role", type=str, default=None, help="Target role filter override")
    scanner_parser.add_argument("--location", type=str, default=None, help="Target location filter override")
    scanner_parser.add_argument("--timeframe", type=str, default=None, help="Search freshness window (e.g. 24h, 48h, 1w)")
    scanner_parser.add_argument("--model", type=str, default=None, help="LLM model override (gemini-*, claude-* or gpt-*; a claude-*/gpt-* name picks that provider as primary)")
    scanner_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    scanner_parser.add_argument("--top-applicant", action="store_true", help="Scan LinkedIn specifically for Top Applicant postings and apply directly without JD scoring")
    scanner_parser.add_argument("--sponsor-only", "--sponsored", dest="sponsor_only", action="store_true", help="Filter and only apply/tailor for verified UK Visa Sponsor employers")
    scanner_parser.add_argument("--skip-portals", type=str, default=None, help="Comma-separated list of job portals/boards to skip (e.g. 'targetjobs,reed,indeed')")
    scanner_parser.add_argument("--harvest", action="store_true", help="Harvest and validate fresh ATS company slugs (Ashby, Greenhouse, Lever) before scanning")

    # 2. Apply subcommand
    apply_parser = subparsers.add_parser(
        "apply",
        help="Run ad-hoc browser auto-filler on a specific job application URL",
    )
    apply_parser.add_argument("target", type=str, help="Job posting URL, or path to a .txt/.json/.csv file containing job URLs")
    apply_parser.add_argument("--submit", action="store_true", help="Auto-submit the application if safe")
    apply_parser.add_argument("--dry-run", action="store_true", help="Fill forms and stop at the review step; never submit (overrides --submit and .env)")
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
    status_parser = subparsers.add_parser(
        "status",
        help="Display system configuration, environment status, master resume, and API keys",
    )
    status_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    config_parser = subparsers.add_parser("config", help="Show where Job Finder stores its profile, logs and tracker, and which settings are set")
    config_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    export_parser = subparsers.add_parser("export", help="Export tracked applications to CSV or JSON")
    export_parser.add_argument("out", help="Output file path")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv)")
    export_parser.add_argument("--status", default="all", help="Only export applications whose status contains this text")

    cover_parser = subparsers.add_parser("cover-letter", help="Generate a validated cover letter for a job")
    cover_parser.add_argument("title", help="Job title")
    cover_parser.add_argument("company", help="Company name")
    cover_parser.add_argument("--jd-file", default=None, help="Job description text file ('-' reads stdin)")
    cover_parser.add_argument("--jd-url", default=None, help="Job posting URL")
    cover_parser.add_argument("--out", default=None, help="Write the letter to this file")
    cover_parser.add_argument("--json", action="store_true", help="Print the full result as JSON")

    # 8. ATS subcommand
    ats_parser = subparsers.add_parser(
        "ats",
        help="Run standalone ATS Health Audit on your candidate profile or master resume",
    )
    ats_parser.add_argument("--resume", type=str, default=None, help="Path to resume file to evaluate (default: active candidate profile)")
    ats_parser.add_argument("--optimize", action="store_true", help="Auto-optimize summary for ATS conversion using AI")
    ats_parser.add_argument("--jd-file", type=str, default=None, help="Score against a job description text file ('-' reads stdin)")
    ats_parser.add_argument("--jd-url", type=str, default=None, help="Score against a job posting URL")
    ats_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    # 9. Tracker subcommand
    tracker_parser = subparsers.add_parser(
        "tracker",
        help="List and inspect tracked applications, saved roles, and tailored resumes",
    )
    tracker_parser.add_argument("--status", type=str, default="all", help="Filter by status text, case-insensitive (all, saved, applied, review, blocked, ...)")
    tracker_parser.add_argument("--limit", type=int, default=20, help="Max entries to list (default: 20, 0 = all)")
    tracker_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    # 10. Company subcommand (Agent-Reach Culture Brief)
    company_parser = subparsers.add_parser(
        "company",
        help="Generate Agent-Reach company culture, WFH vibe, and interview insights brief",
    )
    company_parser.add_argument("name", type=str, help="Target company name (e.g. Google, Qualcomm)")
    company_parser.add_argument("--role", type=str, default="Software Engineer", help="Target role (default: Software Engineer)")

    # 11. Interview subcommand (YouTube transcript & STAR prep)
    interview_parser = subparsers.add_parser(
        "interview",
        help="Generate custom interview prep pack with optional YouTube transcript parsing",
    )
    interview_parser.add_argument("company", type=str, help="Target company name")
    interview_parser.add_argument("--role", type=str, default="Software Engineer", help="Target role")
    interview_parser.add_argument("--youtube", type=str, default=None, help="Optional YouTube technical interview or system design URL")

    # 12. TargetJobs UK subcommand
    tj_parser = subparsers.add_parser(
        "targetjobs",
        help="Search TargetJobs.co.uk graduate & early career IT jobs (UK only)",
    )
    tj_parser.add_argument("keyword", nargs="?", default=None, help="Search keyword / role (default: from candidate profile)")
    tj_parser.add_argument("--location", type=str, default="London", help="UK location filter (default: 'London')")
    tj_parser.add_argument("--timeframe", type=str, default="48h", help="Timeframe filter (default: '48h')")
    tj_parser.add_argument("--limit", type=int, default=15, help="Maximum number of listings to show/process (default: 15)")
    tj_parser.add_argument("--auto-apply", "--auto-submit", dest="auto_apply", action="store_true", help="Automatically autofill and submit applications for discovered TargetJobs listings")
    tj_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    tj_parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")

    # 13. Jobserve Tech & Contract subcommand
    jobserve_parser = subparsers.add_parser(
        "jobserve",
        help="Search Jobserve (jobserve.com) for tech, AI, software engineering, and contract/perm roles",
    )
    jobserve_parser.add_argument("keyword", nargs="?", default=None, help="Search keyword / role (default: from candidate profile)")
    jobserve_parser.add_argument("--location", type=str, default="UK", help="Location filter (default: 'UK')")
    jobserve_parser.add_argument("--timeframe", type=str, default="48h", help="Timeframe filter (default: '48h')")
    jobserve_parser.add_argument("--limit", type=int, default=15, help="Maximum number of listings to show/process (default: 15)")
    jobserve_parser.add_argument("--auto-apply", "--auto-submit", dest="auto_apply", action="store_true", help="Automatically autofill and submit applications for discovered Jobserve listings")
    jobserve_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    jobserve_parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")

    # 14. Follow-up subcommand (LinkedIn Recruiter View 3-Day Follow-Up Engine)
    followup_parser = subparsers.add_parser(
        "follow-up",
        help="Automated 3-day post-application recruiter & profile-view follow-up engine",
    )
    followup_parser.add_argument("--min-days", type=int, default=3, help="Minimum days elapsed since application/view (default: 3 days)")
    followup_parser.add_argument("--views-only", action="store_true", help="Scan LinkedIn profile views for recruiters who viewed profile")
    followup_parser.add_argument("--auto-send", action="store_true", help="Automatically dispatch LinkedIn InMail outreach")
    followup_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly")

    # 14. Harvest-slugs subcommand (Exhaustive Ashby, Greenhouse, Lever ATS slug harvester)
    harvest_parser = subparsers.add_parser(
        "harvest-slugs",
        help="Harvest and validate 10,000+ ATS company board slugs (Ashby, Greenhouse, Lever)",
    )
    harvest_parser.add_argument("--source", type=str, default="seeds", help="Sourcing strategy: seeds, cdx, yc, or all (default: seeds)")
    harvest_parser.add_argument("--ats", type=str, default=None, help="Filter by specific ATS platform: ashby, greenhouse, lever")
    harvest_parser.add_argument("--validate", action="store_true", help="Run live endpoint verification against discovered candidate slugs")
    harvest_parser.add_argument("--limit", type=int, default=100, help="Max unverified slugs to validate (default: 100)")

    # 15. Sponsor subcommand (UK Visa Sponsor Register Checker)
    sponsor_parser = subparsers.add_parser(
        "sponsor",
        help="Check UK visa sponsorship status against official Home Office register",
    )
    sponsor_parser.add_argument("company", nargs="?", default=None, help="Company name to check (e.g. Google, Insight)")
    sponsor_parser.add_argument("--sync", action="store_true", help="Download and sync latest Home Office sponsor register CSV")
    sponsor_parser.add_argument("--stats", action="store_true", help="Display local sponsor database statistics and last sync date")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check keys, browser, CDP port, email and guardrail configuration",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    return parser
