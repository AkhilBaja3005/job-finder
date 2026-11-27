"""Argument parser for the Job Finder CLI (kept separate from the command handlers in cli.py)."""

import argparse

EXAMPLES = """\
examples:
  job-finder setup                       first-time setup (resume, keys, browser login)
  job-finder doctor                      check keys, Chrome, CDP port and email config
  job-finder scan                        discover jobs (topic/level from your profile) into the Excel tracker
  job-finder scan quantum computing internships     say what you want in plain words
  job-finder scan --topic "agentic AI, applied AI" --level intern
  job-finder scan --role "AI Intern"     exact search string, no topic filtering
  job-finder apply --dry-run --limit 3   fill (never submit) the top 3 open rows of the tracker
  job-finder apply --submit --ids 4,7    submit applications for tracker rows 4 and 7
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
        help="Discover jobs and save them to the Excel tracker (does not apply)",
    )
    scanner_parser.add_argument("request", nargs="*", help="What you want, in plain words, e.g.  quantum computing internships  (overrides the profile's topics/level)")
    scanner_parser.add_argument("--topic", type=str, default=None, help="Field(s) to look for, comma-separated, e.g. \"agentic AI, applied AI\" (default: topics in your profile)")
    scanner_parser.add_argument("--level", type=str, default=None, help="intern | graduate | experienced | all | any. Typed a topic/titles but no level = all: every job is filed into the intern, graduate or experienced Excel (default when nothing is typed: level in your profile)")
    scanner_parser.add_argument("--loose", action="store_true", help="Also accept postings whose job description (not just title) matches the topic/level")
    scanner_parser.add_argument("--exact", action="store_true", help="Match only your own topic words; skip LLM synonym expansion")
    scanner_parser.add_argument("--role", type=str, default=None, help="Exact search string(s), comma-separated; no topic filtering (default: target_roles in your profile)")
    scanner_parser.add_argument("--location", type=str, default=None, help="Location override (default: first target_locations entry)")
    scanner_parser.add_argument("--timeframe", type=str, default=None, help="Search freshness window (e.g. 24h, 48h, 1w)")
    scanner_parser.add_argument("--min-ats", type=int, default=None, help="Only save jobs scoring at least this ATS %% (default: save everything found)")
    scanner_parser.add_argument("--limit", type=int, default=0, help="Max new jobs to save, best ATS first (default: 0 = no limit)")
    scanner_parser.add_argument("--no-ai-score", action="store_true", help="Score with the old keyword engine instead of the AI fit analysis (no LLM calls)")
    scanner_parser.add_argument("--no-enrich", action="store_true", help="Quick scan: skip fetching full job descriptions and closing dates")
    scanner_parser.add_argument("--model", type=str, default=None, help="LLM model override (gemini-*, claude-* or gpt-*; a claude-*/gpt-* name picks that provider as primary)")
    scanner_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    scanner_parser.add_argument("--top-applicant", action="store_true", help="Scan LinkedIn specifically for Top Applicant postings and apply directly without JD scoring")
    scanner_parser.add_argument("--sponsor-only", "--sponsored", dest="sponsor_only", action="store_true", help="Filter and only apply/tailor for verified UK Visa Sponsor employers")
    scanner_parser.add_argument("--skip-portals", type=str, default=None, help="Comma-separated list of job portals/boards to skip (e.g. 'targetjobs,reed,indeed')")
    scanner_parser.add_argument("--harvest", action="store_true", help="Harvest and validate fresh ATS company slugs (Ashby, Greenhouse, Lever) before scanning")
    # Retired: scan no longer applies. Kept (hidden) so old commands fail with a pointer to `apply`.
    scanner_parser.add_argument("--search", type=str, default=None, metavar="NAME", help="Repeat a saved search and update ITS Excel (see `job-finder searches`)")
    scanner_parser.add_argument("--into", type=str, default=None, metavar="NAME|FILE.xlsx", help="Add the results to this existing search / Excel file instead of the one this topic would use")
    scanner_parser.add_argument("--name", type=str, default=None, help="Give this search's Excel a name of your choice (default: derived from topic + level)")
    scanner_parser.add_argument("--expand", type=int, default=1, metavar="ROUNDS", help="Rounds of expansion: also search the job titles found so far to surface related roles (default 1, 0 = off)")
    scanner_parser.add_argument("--no-expand", action="store_true", help="Search only the titles/topics you typed (same as --expand 0)")
    scanner_parser.add_argument("--ai-limit", type=int, default=60, help="Max postings to analyse with the LLM per scan (intern + graduate first; default 60) to protect your API quota")
    scanner_parser.add_argument("--core-only", action="store_true", help="Keep only titles that name the exact niche (Match = Core); drop adjacent-field roles (Match = Related)")
    scanner_parser.add_argument("--score-all", action="store_true", help="Also AI-score experienced roles (default: only intern and graduate roles)")
    scanner_parser.add_argument("--no-boards", action="store_true", help="Skip the company-board index (Greenhouse / Lever / Ashby boards)")
    scanner_parser.add_argument("--dry-run", action="store_true", help="Search and filter only: print the whole funnel and every dropped title, write nothing, score nothing")
    for _flag in ("--auto-apply", "--auto-submit"):
        scanner_parser.add_argument(_flag, dest="retired_apply_flag", action="store_true", help=argparse.SUPPRESS)
    for _flag in ("--timeout", "--tailor-timeout", "--max-steps"):
        scanner_parser.add_argument(_flag, dest="retired_apply_opt", default=None, help=argparse.SUPPRESS)

    outcomes_parser = subparsers.add_parser(
        "outcomes",
        help="Show how applications ended, with the success rate for each job site",
    )
    outcomes_parser.add_argument("--json", action="store_true", help="Print results as JSON")
    outcomes_parser.add_argument("--recent", type=int, default=0, help="Also list the last N attempts with their reason and screenshot")

    # 2. Apply subcommand
    apply_parser = subparsers.add_parser(
        "apply",
        help="Run ad-hoc browser auto-filler on a specific job application URL",
    )
    apply_parser.add_argument("target", nargs="?", default=None, help="Optional: a job URL, or a .txt/.json/.csv file of URLs. Omit to apply to the approved queue (approved_jobs.xlsx)")
    apply_parser.add_argument("--ids", type=str, default=None, help="Queue mode: only these row IDs, comma-separated (e.g. 4,7,12)")
    apply_parser.add_argument("--min-ats", type=int, default=None, help="Queue mode: only rows with at least this ATS %% (default: everything you approved)")
    apply_parser.add_argument("--limit", type=int, default=0, help="Queue mode: max applications this run, best ATS first (default: 0 = the whole queue)")
    apply_parser.add_argument("--company", type=str, default=None, help="Queue mode: only companies containing this text")
    apply_parser.add_argument("--retry", action="store_true", help="Queue mode: also retry rows marked Needs Review")
    apply_parser.add_argument("--no-pack", action="store_true", help="Queue mode: skip the review gate; use your master resume and let the agent write any cover letter")
    apply_parser.add_argument("--submit", action="store_true", help="Really submit applications (default is preview: fill the form, never submit)")
    apply_parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt before submitting")
    apply_parser.add_argument("--dry-run", action="store_true", help="Fill forms and stop at the review step; never submit (overrides --submit and .env)")
    apply_parser.add_argument("--timeout", type=float, default=300.0, help="Application timeout in seconds (default: 300s)")
    apply_parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps (default: 50)")
    apply_parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="LLM model to use (default: gemini-3.5-flash-lite)")
    apply_parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    apply_parser.add_argument("--resume", type=str, default=None, help="Path to resume PDF to upload (default: auto-detected master resume)")

    # 2b. Approve subcommand: scanned_jobs.xlsx -> approved_jobs.xlsx
    approve_parser = subparsers.add_parser(
        "approve",
        help="Move jobs you chose from scanned_jobs.xlsx into the approved queue that `apply` works from",
    )
    approve_parser.add_argument("--ids", type=str, default=None, help="Approve (or with --revoke, withdraw) these row IDs, comma-separated")
    approve_parser.add_argument("--min-ats", type=int, default=None, help="Approve every open row scoring at least this ATS %%")
    approve_parser.add_argument("--revoke", action="store_true", help="Take --ids back out of the queue (not if already applied)")
    approve_parser.add_argument("--list", action="store_true", help="Show what is waiting in the approved queue")
    approve_parser.add_argument("--no-prepare", action="store_true", help="Don't build the application packs (tailored CV, cover letter) for newly approved jobs")
    approve_parser.add_argument("--cover-letter", choices=["auto", "always", "never"], default="auto", help="Cover letter for new packs: auto = only when the posting mentions one (default)")

    # 2b2. Topic inspector
    topic_parser = subparsers.add_parser("topic", help="Show what a topic means to `scan` (sub-fields, look-alikes, searches) without searching")
    topic_parser.add_argument("request", nargs="*", help="e.g.  cyber security internships")
    topic_parser.add_argument("--topic", type=str, default=None, help="Topic(s), comma-separated")
    topic_parser.add_argument("--level", type=str, default=None, help="intern | graduate | junior | senior | any")
    topic_parser.add_argument("--refresh", action="store_true", help="Ask the LLM to rebuild the topic's field (replaces the cached/edited one)")

    # 2b3. Prepare / review: the per-job application packs
    prep_parser = subparsers.add_parser("prepare", help="Build the application pack for approved jobs: tailored CV, cover letter if needed, JD, fit analysis")
    prep_parser.add_argument("--ids", type=str, default=None, help="Only these row IDs, comma-separated")
    prep_parser.add_argument("--redo", action="store_true", help="Regenerate from scratch (discards your edits to cv.json / cover_letter.txt)")
    prep_parser.add_argument("--render-only", action="store_true", help="Rebuild the PDFs from your edited cv.json / cover_letter.txt without calling the LLM")
    prep_parser.add_argument("--cover-letter", choices=["auto", "always", "never"], default="auto", help="auto = only when the posting mentions a cover letter (default)")
    review_parser = subparsers.add_parser("review", help="List application packs, open one, and sign off (Docs OK) so `apply` may use it")
    review_parser.add_argument("--open", type=int, default=None, metavar="ID", help="Open this job's pack folder")
    review_parser.add_argument("--ok", type=str, default=None, help="Sign off these IDs (comma-separated): you reviewed the CV / cover letter")
    review_parser.add_argument("--revoke", type=str, default=None, help="Take the sign-off back for these IDs")

    # 2b4. Company-board index
    boards_parser = subparsers.add_parser("boards", help="Build/inspect the index of open London/UK jobs on thousands of Greenhouse, Lever and Ashby boards")
    boards_parser.add_argument("action", choices=["refresh", "status"], help="refresh = (re)visit the boards, status = show what is indexed")
    boards_parser.add_argument("--ats", type=str, default=None, help="Comma-separated subset: greenhouse,lever,ashby")
    boards_parser.add_argument("--limit", type=int, default=None, help="Only visit this many boards (to try it out)")
    boards_parser.add_argument("--force", action="store_true", help="Re-visit every board, ignoring how recently it was checked")
    boards_parser.add_argument("--location", type=str, default=None, help="City to index (default: first target_locations entry)")
    boards_parser.add_argument("--concurrency", type=int, default=24, help="Parallel requests (default 24)")

    # 2b5. searches: one Excel per search
    searches_parser = subparsers.add_parser("searches", help="List searches (one Excel each), switch the current one, or move jobs between them")
    searches_parser.add_argument("action", nargs="?", choices=["list", "use", "move", "path"], default="list")
    searches_parser.add_argument("name", nargs="?", default=None, help="Search name for `use` / `path` (a unique prefix is enough)")
    searches_parser.add_argument("--from", dest="source", type=str, default=None, help="move: source search")
    searches_parser.add_argument("--to", type=str, default=None, help="move: target search (created if it does not exist)")
    searches_parser.add_argument("--ids", type=str, default=None, help="move: job IDs, e.g. 3,5,8-10")

    # 2c. Open subcommand
    open_parser = subparsers.add_parser("open", help="Open the scanned or approved Excel file")
    open_parser.add_argument("which", nargs="?", choices=["scanned", "approved"], default="scanned", help="Which workbook (default: scanned)")

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
    ats_parser.add_argument("--keyword", action="store_true", help="Use the old fixed-keyword engine instead of the AI analysis (audit and --jd-file/--jd-url)")
    ats_parser.add_argument("--add-skills", action="store_true", help="After the audit, add skills your profile evidences but doesn't list to core_skills (asks first, backs up)")
    ats_parser.add_argument("--yes", "-y", action="store_true", help="With --add-skills: skip the confirmation prompt")
    ats_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    # 9. Tracker subcommand
    tracker_parser = subparsers.add_parser(
        "tracker",
        help="List and inspect tracked applications, saved roles, and tailored resumes",
    )
    tracker_parser.add_argument("--approved", action="store_true", help="Show the approved queue instead of the scanned jobs")
    tracker_parser.add_argument("--status", type=str, default="all", help="Filter by status text, case-insensitive (all, saved, applied, review, blocked, ...)")
    tracker_parser.add_argument("--limit", type=int, default=20, help="Max entries to list (default: 20, 0 = all)")
    tracker_parser.add_argument("--json", action="store_true", help="Print results as JSON")

    for _p in (approve_parser, prep_parser, review_parser, apply_parser, open_parser, tracker_parser):
        _p.add_argument("--search", type=str, default=None, metavar="NAME", help="Work on this search's Excel instead of the current one (see `job-finder searches`)")

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
