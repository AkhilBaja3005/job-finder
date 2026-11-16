"""`job-finder setup` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    print("\n========================================================")
    print("          JOB FINDER AI - QUICK SETUP WIZARD")
    print("========================================================\n")
    from backend.config.constants import resolve_workspace_root
    from backend.job_finder_mcp.tools.profile_tools import get_profile_config_path, get_profile_save_path

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
            print(f"Initialized .env configuration from template: {env_path}")
        else:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Job Finder AI Environment Configuration\n"
                    "PORT=8000\n"
                    "SCRAPER_CONCURRENCY=5\n"
                    "BROWSER_USE_HEADLESS=false\n"
                    "JOB_FINDER_DISABLE_GUARDRAILS=0\n"
                    "SMTP_USER=\n"
                    "SMTP_PASSWORD=\n"
                    "EMAIL_FROM=\n"
                )
            print(f"Created initial .env configuration file: {env_path}")

    else:
        print(f"Found existing .env at {env_path}")

    # Ensure baseline keys are present in .env
    with open(env_path, "r", encoding="utf-8") as ef:
        existing_env_txt = ef.read()

    missing_defaults = []
    if "BROWSER_USE_HEADLESS=" not in existing_env_txt:
        missing_defaults.append("BROWSER_USE_HEADLESS=false\n")
    if "JOB_FINDER_DISABLE_GUARDRAILS=" not in existing_env_txt:
        missing_defaults.append("JOB_FINDER_DISABLE_GUARDRAILS=0\n")
    if "SMTP_USER=" not in existing_env_txt:
        missing_defaults.append("SMTP_USER=\n")
        missing_defaults.append("SMTP_PASSWORD=\n")
        missing_defaults.append("EMAIL_FROM=\n")

    if missing_defaults:
        with open(env_path, "a", encoding="utf-8") as ef:
            ef.write("\n" + "".join(missing_defaults))

    # Configure GEMINI_API_KEY
    existing_key = os.getenv("GEMINI_API_KEY")
    if args.api_key:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nGEMINI_API_KEY={args.api_key}\n")
        os.environ["GEMINI_API_KEY"] = args.api_key
        print("Configured GEMINI_API_KEY into .env")
    elif not existing_key:
        if sys.stdin.isatty():
            print("\nGemini API Key is required for resume parsing, ATS scoring & browser automation.")
            print("   (Get a free key at https://aistudio.google.com/)")
            try:
                user_key = input("  Enter your GEMINI_API_KEY: ").strip()
                if user_key:
                    with open(env_path, "a", encoding="utf-8") as f:
                        f.write(f"\nGEMINI_API_KEY={user_key}\n")
                    os.environ["GEMINI_API_KEY"] = user_key
                    print("GEMINI_API_KEY saved to .env")
            except (EOFError, KeyboardInterrupt):
                print("\nSkipping API key prompt.")
        else:
            print(" GEMINI_API_KEY is not set in environment or .env. You can pass it via `job-finder setup --api-key <KEY>`")
    else:
        masked = existing_key[:4] + "..." + existing_key[-4:] if len(existing_key) > 8 else "***"
        print(f"Gemini API Key configured ({masked})")

    # Configure SMTP Notifications (Optional)
    existing_smtp_user = os.getenv("SMTP_USER")
    if sys.stdin.isatty():
        if not existing_smtp_user:
            print("\nEmail Notifications for Applied & Review Alerts (Optional)")
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
                        print("SMTP email notifications configured in .env")
            except (EOFError, KeyboardInterrupt):
                print("\nSkipping email configuration.")

    # 2. Initialize candidate_profile.json in workspace root
    if not os.path.exists(profile_path) and example_profile and os.path.exists(example_profile):
        import shutil
        os.makedirs(os.path.dirname(profile_path), exist_ok=True)
        shutil.copy2(example_profile, profile_path)
        print(f"Initialized candidate_profile.json in workspace: {profile_path}")
    elif os.path.exists(profile_path):
        print(f"Found existing candidate profile at: {profile_path}")


    # 3. Master Resume Path Configuration & Profile Sync
    existing_master = os.getenv("MASTER_RESUME_PATH")
    resume_target = args.resume

    if resume_target:
        resume_target = os.path.abspath(os.path.expanduser(resume_target.strip('\'"')))
    elif sys.stdin.isatty():
        print("\n========================================================")
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
            print(f"Saved MASTER_RESUME_PATH in .env: {resume_target}")
        except Exception as env_err:
            print(f"Could not write MASTER_RESUME_PATH to .env: {env_err}")

        print(f"Syncing candidate profile from resume: {resume_target}")
        import asyncio
        from backend.job_finder_mcp.tools.profile_tools import handle_sync_candidate_profile_from_resume
        res = asyncio.run(handle_sync_candidate_profile_from_resume({"resume_path": resume_target}))
        if res.get("success"):
            print(f"Extracted: {res.get('skills_count')} skills, {res.get('experience_count')} work experiences, {res.get('education_count')} education entries.")
            
            # Run ATS Health Audit & Display Improvement Tips
            try:
                from backend.services.ats_scorer import evaluate_master_resume
                from backend.job_finder_mcp.tools.profile_tools import load_profile_data, save_profile_data
                profile_data = load_profile_data()
                ats_eval = evaluate_master_resume(profile_data.get("candidate", {}))
                ats_score = ats_eval.get("ats_score", 80)
                suggestions = ats_eval.get("suggestions", [])

                print("\n========================================================")
                print(f"           MASTER RESUME ATS HEALTH SCORE: {ats_score}/100")
                print("========================================================")
                print(f"  • Skill Keywords  : {ats_eval.get('skills_count')} core taxonomy matches")
                print(f"  • Quantified Ratio: {ats_eval.get('quantified_percentage')}% of bullets contain metrics (%, £/$, numbers)")
                print(f"  • Estimated Tenure: {ats_eval.get('candidate_years')} years relevant experience")

                if suggestions:
                    print("\nKey ATS Improvement Tips:")
                    for tip in suggestions:
                        print(f"  • {tip}")

                # Interactive prompt to auto-enhance summary if suggestions exist
                if sys.stdin.isatty() and suggestions:
                    try:
                        print("\nWould you like AI to auto-optimize your summary to improve ATS conversion? [Y/n]: ", end="")
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
                                print(f"\nAuto-Optimized Summary Saved:\n  \"{cand['experience_summary']}\"")
                    except (EOFError, KeyboardInterrupt):
                        print("\nSkipping summary optimization.")
            except Exception as ats_err:
                print(f"Could not compute ATS baseline: {ats_err}")
        else:
            print(f"Could not auto-parse resume: {res.get('error')}")
    elif resume_target and not os.path.exists(resume_target):
        print(f"Provided resume file does not exist: {resume_target}")
        print("Tip: Run `job-finder profile --sync /path/to/resume.pdf` anytime to import your full resume.")
    else:
        print("Tip: Run `job-finder profile --sync /path/to/resume.pdf` anytime to import your full resume.")

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

            print("\n========================================================")
            print("     CANDIDATE PROFILE DATA PROVENANCE & REVIEW")
            print("========================================================")
            print("  From Resume : Name, Contact Info, Work Experience, Education & Skills")
            print("  From Template: Demographic & compliance fields not present on standard resumes")
            if default_derived_fields:
                print("\n  The following fields were initialized from defaults. Please verify them:")
                for k, lbl, cur in default_derived_fields:
                    print(f"    • {lbl} ({k}): {cur}")

            if unfilled_fields:
                print("\n The following fields are EMPTY or PLACEHOLDERS and require your input:")
                for k, lbl, _ in unfilled_fields:
                    print(f"    • {lbl} ({k})")

            # If interactive terminal session, prompt user to review or update
            fields_to_prompt = unfilled_fields + default_derived_fields
            if sys.stdin.isatty():
                print("\nWould you like to review or update any of these fields now?")
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
                    print(f"\nUpdated candidate profile saved to: {profile_path}")
            else:
                print(f"\nNote: Review or edit these anytime in `{profile_path}` or run `job-finder profile`.")
        except Exception as pe:
            print(f"Could not inspect candidate profile: {pe}")

    # 5. Interactive Dedicated Browser Setup for One-Time Login (LinkedIn, Indeed, Gmail)
    if sys.stdin.isatty():
        print("\n========================================================")
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
                    print("\nLaunching dedicated automation browser...")
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
                        try:
                            subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                        except Exception:
                            pass

                    print("\nDedicated Automation Browser window opened!")
                    print("   Look for the Google Chrome window that opened LinkedIn, Indeed, and Gmail.")
                    print("   (This window runs on a dedicated profile so it won't affect your personal browser).")
                    input("   Press [Enter] when you have finished logging in to proceed... ")
                except Exception as b_err:
                    print(f"Could not launch automation browser automatically: {b_err}")

        except (EOFError, KeyboardInterrupt):
            print("\nSkipping browser login setup.")

    print("\nSetup complete! You're ready to run:")
    print("   - `job-finder profile --show` : Review your parsed candidate profile")
    print("   - `job-finder scan`           : Run autonomous job search and ATS tailoring")
    print("   - `job-finder server`         : Start web dashboard on http://localhost:8000")
    print("   - `job-finder mcp`            : Run MCP server for Claude/Cursor IDE\n")
