"""Unified CLI dispatcher for Job Finder AI."""

import argparse
import sys
import os
import json
import re

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
    REPO_ROOT,
    os.path.join(REPO_ROOT, "backend"),
    os.path.join(REPO_ROOT, "site-packages", "backend"),
    os.path.dirname(os.path.abspath(__file__)),
]:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)


def check_for_updates():
    """
    Non-blocking update check against PyPI / GitHub releases with local cache.
    Caches check result for 24 hours to prevent network overhead on every CLI invocation.
    """
    try:
        import time
        import urllib.request
        from importlib.metadata import version as get_pkg_version

        from backend.config.constants import APP_VERSION
        current_ver = APP_VERSION
        try:
            current_ver = get_pkg_version("job-finder-ai")
        except Exception:
            pass

        cache_file = os.path.expanduser("~/.config/job-finder/.update_check.json")
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        now = time.time()

        # Read cache
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                latest = cdata.get("latest_version")
                last_check = cdata.get("last_check", 0)
                # If checked within 24h (86400s), reuse cached latest version
                if now - last_check < 86400 and latest:
                    if _parse_ver(latest) > _parse_ver(current_ver):
                        print(f"💡 Update available: v{current_ver} → v{latest}. Run 'pip install --upgrade job-finder-ai' to update.\n")
                    return
            except Exception:
                pass

        # Fetch latest version from PyPI with a strict 1.5s timeout
        req = urllib.request.Request("https://pypi.org/pypi/job-finder-ai/json", headers={"User-Agent": "job-finder-cli"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latest_ver = data.get("info", {}).get("version", current_ver)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"latest_version": latest_ver, "last_check": now}, f)

        if _parse_ver(latest_ver) > _parse_ver(current_ver):
            print(f"💡 Update available: v{current_ver} → v{latest_ver}. Run 'pip install --upgrade job-finder-ai' to update.\n")
    except Exception:
        pass


def _parse_ver(v_str: str):
    """Simple tuple version parser (e.g. '1.2.4' -> (1, 2, 4))."""
    try:
        parts = []
        for x in v_str.strip().lstrip("v").split("."):
            num = re.search(r'\d+', x)
            parts.append(int(num.group()) if num else 0)
        return tuple(parts)
    except Exception:
        return (0, 0, 0)


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
    apply_parser.add_argument("target", type=str, help="Job posting URL, or path to a .txt/.json/.csv file containing job URLs")
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

    args, unknown = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        check_for_updates()
        sys.exit(0)

    # Check for available package updates unless in quiet/mcp stdio mode
    if args.subcommand != "mcp":
        check_for_updates()

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
        import re
        from applications_tracker.scheduled_job_scanner import run_browser_use_autofill, find_master_resume_with_mac_tags
        from backend.mcp.tools.profile_tools import load_profile_data

        urls_to_process = []
        target_path = args.target.strip()

        if os.path.exists(target_path) and os.path.isfile(target_path):
            print(f"[Apply Batch] Reading URLs from file: {target_path}")
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    content = f.read()

                if target_path.lower().endswith(".json"):
                    data = json.loads(content)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, str) and item.startswith("http"):
                                urls_to_process.append(item)
                            elif isinstance(item, dict):
                                u = item.get("url") or item.get("job_url") or item.get("link")
                                if u:
                                    urls_to_process.append(u)
                    elif isinstance(data, dict):
                        u_list = data.get("urls") or data.get("jobs") or []
                        for item in u_list:
                            if isinstance(item, str):
                                urls_to_process.append(item)
                            elif isinstance(item, dict):
                                u = item.get("url") or item.get("job_url")
                                if u:
                                    urls_to_process.append(u)
                else:
                    # Parse .txt or .csv files by extracting HTTP/HTTPS links
                    found = re.findall(r'https?://[^\s,"]+', content)
                    urls_to_process = [u.rstrip(")") for u in found]
            except Exception as fe:
                print(f"[Error] Failed to parse batch file '{target_path}': {fe}")
                sys.exit(1)
        elif target_path.startswith("http://") or target_path.startswith("https://"):
            urls_to_process = [target_path]
        else:
            print(f"[Error] '{target_path}' is neither a valid HTTP/HTTPS URL nor an existing file path.")
            sys.exit(1)

        if not urls_to_process:
            print(f"[Warning] No valid HTTP/HTTPS job URLs found in '{target_path}'.")
            sys.exit(0)

        # Deduplicate preserving order
        urls_to_process = list(dict.fromkeys(urls_to_process))

        # Check against local tracker & Supabase to skip previously applied roles
        try:
            from applications_tracker.scheduled_job_scanner import get_existing_tracked_urls, normalize_job_url
            existing_tracked = get_existing_tracked_urls()
            unapplied_urls = []
            skipped_count = 0
            for u in urls_to_process:
                norm_u = normalize_job_url(u)
                if norm_u and norm_u in existing_tracked:
                    skipped_count += 1
                else:
                    unapplied_urls.append(u)

            if skipped_count > 0:
                print(f"[Tracker] ⏭️ Skipped {skipped_count} URL(s) that were already applied/tracked in database.")
            urls_to_process = unapplied_urls
        except Exception as te:
            print(f"[Tracker] Note: Tracker duplicate check skipped: {te}")

        if not urls_to_process:
            print(f"[Apply] All URLs in '{target_path}' have already been applied to!")
            sys.exit(0)

        print(f"[Apply] Ready to process {len(urls_to_process)} job application URL(s).")

        prof = load_profile_data() or {}
        cand = prof.get("candidate", {})
        target_resume = args.resume or find_master_resume_with_mac_tags()

        failed_jobs = []
        successful_jobs = []

        async def _batch_apply():
            nonlocal failed_jobs, successful_jobs
            from mcp.tools.tracking_tools import handle_track_application

            for idx, url in enumerate(urls_to_process, 1):
                print(f"\n========================================================")
                print(f"[{idx}/{len(urls_to_process)}] Processing Application: {url}")
                print(f"========================================================\n")
                status = "failed"
                err_text = ""
                try:
                    res = await asyncio.wait_for(
                        run_browser_use_autofill(
                            url,
                            resume_data=cand,
                            resume_pdf_path=target_resume,
                            auto_submit=args.submit,
                            model_name=args.model,
                            headless=args.headless,
                            max_steps=args.max_steps
                        ),
                        timeout=args.timeout
                    )
                    res_status = str(res.get("status", "")).lower() if isinstance(res, dict) else ""
                    final_res = str(res.get("final_result", "")) if isinstance(res, dict) else str(res)

                    if "submitted" in res_status or "confirmed" in final_res.lower() or "applied" in final_res.lower():
                        status = "applied"
                        successful_jobs.append(url)
                        print(f"[{idx}/{len(urls_to_process)} Success] Application completed for: {url}")
                    else:
                        status = "failed"
                        err_text = res.get("error") or final_res or "Autofill incomplete"
                        failed_jobs.append({"url": url, "reason": err_text})
                        print(f"[{idx}/{len(urls_to_process)} Failed] {err_text}")
                except asyncio.TimeoutError:
                    err_text = f"Application timed out after {int(args.timeout)}s"
                    status = "failed"
                    failed_jobs.append({"url": url, "reason": err_text})
                    print(f"[{idx}/{len(urls_to_process)} Error] {err_text}")
                except Exception as ex:
                    err_text = str(ex)
                    status = "failed"
                    failed_jobs.append({"url": url, "reason": err_text})
                    print(f"[{idx}/{len(urls_to_process)} Error] Failed to process {url}: {ex}")

                # Formally record the application state (failed or applied) into the database & CSV tracker
                try:
                    handle_track_application(
                        job_url=url,
                        status=status,
                        job_title="Target Role",
                        company="Company",
                        score=0
                    )
                except Exception as trk_err:
                    print(f"[Tracker] Note: Could not record application state: {trk_err}")

        asyncio.run(_batch_apply())

        print(f"\n========================================================")
        print(f"   BATCH APPLICATION SUMMARY")
        print(f"========================================================")
        print(f"Total Processed: {len(urls_to_process)}")
        print(f"Successful     : {len(successful_jobs)}")
        print(f"Failed         : {len(failed_jobs)}")
        if failed_jobs:
            print(f"\nFailed Application Details:")
            for f_item in failed_jobs:
                print(f"  ❌ {f_item['url']}")
                print(f"     Reason: {f_item['reason']}")
        print(f"========================================================\n")

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
                print(f"Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
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

        print("\n========================================================")
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
                "CRITICAL: You MUST explicitly include candidate's core technical keywords (e.g. LLMs, RAG, Vector Search, PyTorch, Python, GenAI) and quantified metrics (%, latency cuts, user volume).\n"
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
                print(f"✅ Auto-Optimized Summary Saved:\n  \"{cand['experience_summary']}\"")
                
                # Re-evaluate ATS health score after optimization
                post_eval = evaluate_master_resume(cand)
                post_score = post_eval.get("ats_score", 80)
                print(f"📈 Updated Master Resume ATS Health Score: {post_score}/100 ({post_eval.get('skills_count')} taxonomy keywords matched)\n")

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

    elif args.subcommand == "company":
        from backend.services.agent_reach_service import generate_enhanced_company_brief
        print(f"⏳ Fetching Agent-Reach community culture brief for '{args.name}'...")
        res = generate_enhanced_company_brief(args.name, args.role)
        if res.get("status") == "success":
            print(f"\n🏢 ========================================================")
            print(f"    AGENT-REACH COMPANY BRIEF: {args.name.upper()} ({args.role})")
            print("========================================================\n")
            print(res.get("brief_markdown", ""))
        else:
            print(f"❌ Could not fetch company brief: {res.get('message')}")

    elif args.subcommand == "interview":
        from backend.services.session_store import get_session_data
        from backend.services.gemini_client import generate_content_with_fallback
        from backend.services.agent_reach_service import extract_youtube_transcript

        session = get_session_data("guest")
        cand_data = session.get("data", {})
        
        yt_transcript = ""
        if args.youtube:
            print(f"📹 Parsing YouTube interview transcript from: {args.youtube}...")
            yt_res = extract_youtube_transcript(args.youtube)
            if yt_res.get("status") == "success":
                yt_transcript = yt_res.get("transcript", "")
                print(f"✅ Extracted {len(yt_transcript)} chars of technical interview transcript via {yt_res.get('source')}.")

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

        print(f"🧠 Generating Interview Prep Pack for {args.company}...")
        prep_md = generate_content_with_fallback(prompt, model_tier="lite")
        print(f"\n🎯 ========================================================")
        print(f"    INTERVIEW PREP PACK: {args.company.upper()} ({args.role})")
        print("========================================================\n")
        print(prep_md)


    elif args.subcommand == "targetjobs":
        import asyncio
        from services.job_searcher import search_targetjobs_uk
        from utils.location_resolver import resolve_location_country
        from backend.mcp.tools.profile_tools import load_profile_data

        # 1. Resolve keyword from candidate profile if not explicitly passed
        keyword = args.keyword
        profile = load_profile_data() or {}
        search_prefs = profile.get("search_preferences", {})
        cand_info = profile.get("candidate", {})

        if not keyword:
            target_roles = search_prefs.get("target_roles", [])
            if target_roles:
                keyword = target_roles[0]
            elif cand_info.get("headline"):
                keyword = cand_info["headline"]
            else:
                keyword = "Software Engineer"

        country = resolve_location_country(args.location)
        if country != "GB":
            print(f"\n[Warning] TargetJobs only serves jobs in the United Kingdom. '{args.location}' resolved to country code '{country}'.")
            print("   Please provide a UK location (e.g. London, Manchester, Leeds, Edinburgh, or UK).\n")
            sys.exit(1)

        print(f"\n========================================================")
        print(f"   TARGETJOBS UK: Graduate & Early Career IT Search")
        print(f"   Keyword: '{keyword}' (from {'CLI arg' if args.keyword else 'candidate profile'}) | Location: '{args.location}'")
        if args.auto_apply:
            print(f"   Mode: Auto-Submit Enabled (Guardrails Disabled)")
        print(f"========================================================\n")

        results = asyncio.run(search_targetjobs_uk(
            keyword=keyword,
            location=args.location,
            timeframe=args.timeframe
        ))

        if not results:
            print(f"No active graduate tech jobs found on TargetJobs.co.uk matching '{keyword}' in {args.location}.\n")
        else:
            display_limit = args.limit or 15
            selected_jobs = results[:display_limit]
            print(f"Found {len(results)} graduate technology postings on TargetJobs (showing top {len(selected_jobs)}):\n")
            for idx, job in enumerate(selected_jobs, start=1):
                print(f"[{idx}] {job.title}")
                print(f"    Company  : {job.company}")
                print(f"    Location : {job.location}")
                print(f"    Apply URL: {job.url}")
                if hasattr(job, 'full_description') and job.full_description:
                    snippet = job.full_description.replace('\n', ' ')[:140]
                    print(f"    Summary  : {snippet}...")
                print()

            if args.auto_apply:
                from applications_tracker.scheduled_job_scanner import apply_to_job, find_master_resume_with_mac_tags
                os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
                master_resume_pdf = find_master_resume_with_mac_tags()
                print(f"Starting automatic submission for {len(selected_jobs)} TargetJobs role(s)...")

                async def _apply_all():
                    for idx, j in enumerate(selected_jobs, 1):
                        print(f"\n[{idx}/{len(selected_jobs)}] Auto-submitting application: {j.title} @ {j.company}")
                        try:
                            await apply_to_job(
                                url=j.url,
                                candidate=cand_info,
                                resume_path=master_resume_pdf,
                                title=j.title,
                                company=j.company,
                                auto_submit=True,
                                timeout_seconds=args.timeout,
                                headless_override=args.headless
                            )
                        except Exception as app_err:
                            print(f"[Warning] Auto-submit failed for {j.title}: {app_err}")

                asyncio.run(_apply_all())
            else:
                print(f"Tip: Run `job-finder targetjobs --auto-submit --limit 3` to auto-apply to these roles!")
                print(f"Or run `job-finder scan --location London, UK` for full unified scanning & tailoring.\n")


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

        # 5. Interactive Dedicated Browser Setup for One-Time Login (LinkedIn, Indeed, Gmail)
        if sys.stdin.isatty():
            print("\n🌐 ========================================================")
            print("         DEDICATED AUTOMATION BROWSER SETUP")
            print("========================================================")
            print("  Job Finder uses a dedicated Chrome profile (`browser_use_chrome_session`)")
            print("  for automated job discovery and application auto-filling.")
            print("  Log in ONCE to LinkedIn, Indeed, and Gmail so the AI agent runs seamlessly.")
            try:
                open_browser_setup = input("  Would you like to open the Automation Browser now to log in? [Y/n]: ").strip().lower()
                if open_browser_setup in ("y", "yes", ""):
                    try:
                        from backend.services.browser_use_agent import ensure_persistent_browser, CDP_PORT
                        print("\n🌐 Launching dedicated automation browser...")
                        cdp_url = ensure_persistent_browser(headless=False)
                        
                        import urllib.request
                        urls_to_open = [
                            "https://www.linkedin.com/login",
                            "https://uk.indeed.com/",
                            "https://mail.google.com/"
                        ]
                        print("  Opening tabs in Automation Chrome profile: LinkedIn, Indeed, Gmail...")
                        for u in urls_to_open:
                            try:
                                req = urllib.request.Request(f"{cdp_url}/json/new?{u}", data=b"", method="PUT")
                                with urllib.request.urlopen(req, timeout=3) as resp:
                                    tab_data = json.load(resp)
                                    tab_id = tab_data.get("id")
                                    if tab_id:
                                        try:
                                            with urllib.request.urlopen(f"{cdp_url}/json/activate/{tab_id}", timeout=2):
                                                pass
                                        except Exception:
                                            pass
                            except Exception as u_err:
                                pass
                        
                        # Bring Chrome to the front
                        if sys.platform == "darwin":
                            import subprocess
                            subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                        print("\n✅ Dedicated Automation Browser window opened!")
                        print("   👉 Look for the Google Chrome window that opened LinkedIn, Indeed, and Gmail.")
                        print("   👉 (This window runs on a dedicated profile so it won't affect your personal browser).")
                        input("   Press [Enter] when you have finished logging in to proceed... ")
                    except Exception as b_err:
                        print(f"⚠️ Could not launch automation browser automatically: {b_err}")

            except (EOFError, KeyboardInterrupt):
                print("\nSkipping browser login setup.")

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
