"""
browser_use_agent.py — Autonomous Job Application Autofill using browser-use & Gemini Flash / Flash-Lite.

Uses browser-use to navigate multi-step job application portals (Ashby, Greenhouse, Lever, Workday),
inspect visual DOM structures, auto-populate candidate details, upload resumes, and answer screening questions.
"""

import os
import sys
import json
import asyncio
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from browser_use import Agent, Browser, ChatGoogle
from config.constants import DEFAULT_FAST_LITE_MODELS, PREFERRED_GEMINI_MODEL

# ─────────────────────────────────────────────────────────────────────────────
# GUARDRAIL CONTROL FLAG
#
# Set DISABLE_GUARDRAILS = True  → agent will autonomously submit applications
#                                  without pausing for human review.
# Set DISABLE_GUARDRAILS = False → agent stops at final review/preview step
#                                  and never clicks the Submit button.
#
# This can also be controlled via the environment variable:
#   BROWSER_USE_DISABLE_GUARDRAILS=1  (any non-empty/non-zero value enables it)
# ─────────────────────────────────────────────────────────────────────────────
DISABLE_GUARDRAILS: bool = os.getenv("BROWSER_USE_DISABLE_GUARDRAILS", "0").strip() not in ("", "0", "false", "False", "no")


def get_browser_use_llm(model_name: Optional[str] = None, custom_api_key: Optional[str] = None):
    """
    Initializes browser-use native ChatGoogle client targeting Gemini Flash-Lite / Flash.
    """
    try:
        from services.gemini_client import get_next_gemini_api_key
        api_key = get_next_gemini_api_key(custom_api_key)
    except Exception:
        api_key = custom_api_key or os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for browser-use agent execution.")

    target_model = model_name or os.getenv("BROWSER_USE_MODEL", "gemini-3.5-flash-lite")
    
    return ChatGoogle(
        model=target_model,
        api_key=api_key,
        temperature=0.1,
    )


def build_application_task_prompt(
    job_url: str,
    resume_data: Dict[str, Any],
    resume_pdf_path: Optional[str] = None,
    auto_submit: bool = False
) -> str:
    """
    Synthesizes candidate background, strict instructions, and safety constraints into an agent prompt.
    """
    candidate_name = resume_data.get("name") or resume_data.get("candidate", {}).get("name", "Applicant")
    email = resume_data.get("email") or resume_data.get("candidate", {}).get("email", "")
    phone = resume_data.get("phone") or resume_data.get("candidate", {}).get("phone", "")
    location = resume_data.get("location") or resume_data.get("candidate", {}).get("location", "")
    postal_code = resume_data.get("postal_code") or resume_data.get("postcode") or resume_data.get("candidate", {}).get("postal_code") or resume_data.get("candidate", {}).get("postcode", "W12 0BZ")
    linkedin = resume_data.get("linkedin") or resume_data.get("candidate", {}).get("linkedin", "")
    github = resume_data.get("github") or resume_data.get("candidate", {}).get("github", "")
    portfolio = resume_data.get("portfolio") or resume_data.get("candidate", {}).get("portfolio", "https://akhilbaja3005.github.io/AkhilBaja3005/")
    summary = resume_data.get("summary") or resume_data.get("candidate", {}).get("experience_summary", "")

    # Demographic & compliance answers commonly asked on job forms
    gender = resume_data.get("gender") or resume_data.get("candidate", {}).get("gender", "Male")
    ethnicity = resume_data.get("ethnicity") or resume_data.get("candidate", {}).get("ethnicity", "Asian")
    citizenship = resume_data.get("citizenship") or resume_data.get("candidate", {}).get("citizenship", "Indian")
    work_auth = resume_data.get("work_authorization") or resume_data.get("candidate", {}).get("work_authorization", "Authorized to work in the UK and India")
    requires_sponsorship = resume_data.get("requires_sponsorship", False)
    sponsorship_str = "Yes" if requires_sponsorship else "No"
    veteran_status = resume_data.get("veteran_status") or resume_data.get("candidate", {}).get("veteran_status", "No")
    disability_status = resume_data.get("disability_status") or resume_data.get("candidate", {}).get("disability_status", "No")
    # Phone parsing for easy international code selection
    phone_digits = "".join(c for c in phone if c.isdigit() or c == '+')
    country_code_hint = "India (+91)" if "+91" in phone_digits or "91" in phone_digits[:4] else "United Kingdom (+44)"
    clean_mobile = phone_digits.replace("+91", "").replace("+44", "").strip()

    task = f"""
    Navigate to the job application URL: {job_url}
    
    You are an ultra-fast, expert AI Career Assistant acting on behalf of the applicant to fill out this job application form.
    
    Applicant Profile Details:
    - Full Name: {candidate_name}
    - Email Address: {email}
    - Phone Number: {phone} (Country Code: {country_code_hint}, Local Number: {clean_mobile})
    - Current Location: {location}
    - Postal Code / Postcode: {postal_code}
    - LinkedIn Profile: {linkedin}
    - GitHub Profile: {github}
    - Portfolio / Website: {portfolio}
    - Gender: {gender}
    - Race / Ethnicity: {ethnicity}
    - Citizenship: {citizenship}
    - Work Authorization: {work_auth}
    - Requires Visa Sponsorship: {sponsorship_str}
    - Protected Veteran Status: {veteran_status}
    - Disability Status: {disability_status}
    - Professional Background: {summary}
    """

    if resume_pdf_path and os.path.exists(resume_pdf_path):
        task += f"\n- Resume File to attach: {os.path.abspath(resume_pdf_path)}\n"

    submission_instruction = (
        "5. SUBMIT APPLICATION: Once all required inputs, attachments, and questions on the final review step are satisfied, click the final 'Submit Application' or 'Send Application' button. Do not add wait steps after submitting."
        if auto_submit
        else "5. SAFETY GUARDRAIL: Navigate through intermediate pages ('Next' / 'Continue'), but DO NOT click final 'Submit Application' or 'Send Application'. Stop on the final review/preview step and report a summary of completed fields."
    )

    task += f"""
    CRITICAL SPEED & EFFICIENCY RULES:
    - DO NOT USE THE WAIT ACTION: The browser environment automatically handles DOM mutations and page loads. Never use `wait: seconds: ...`. Elements are immediately actionable.
    - BATCH ALL ACTIONS: Fill out ALL inputs, selects, and checkboxes on the visible screen in a single turn together with the 'Next' or 'Continue' click. Do not submit one field per step!
    - SELECT DROPDOWNS: Never click HTML `<select>` elements directly. Always use `select_dropdown` with the target text (e.g., text: '{country_code_hint}').
    - NEW TAB HANDLING: If clicking 'Apply' or a link opens an external ATS site (Ashby, Greenhouse, Lever, Workday) in a new tab, ALWAYS stay in that new tab and fill the form there. NEVER switch back to the referrer/LinkedIn tab.

    Execution Instructions:
    1. Early Check for Already Applied or Closed Job:
       - If the page or modal displays 'Job not found', 'This job has closed', 'No longer accepting applications', or 'Applied', immediately call `done` with that reason without wasting extra steps.
    2. Open Form: Click 'Apply', 'Easy Apply', or 'Apply for this job'.
    3. Fill & Advance: In a single batched step, fill all contact/question inputs on the screen and click 'Next' or 'Continue'.
       - For Phone Country Code, select '{country_code_hint}'.
       - For Phone Number input, type '{clean_mobile or phone}'.
       - For Resume, ensure the candidate's resume is selected or uploaded.
       - For Sponsorship question: select 'Yes' ({sponsorship_str}).
       - For Experience years questions: enter truthful estimates based on profile (e.g., 3-5 years for AI/LLM, 0 for unrelated legacy tools).
    4. Review & Conclude:
    {submission_instruction}
    """
    return task


_shared_browser_session: Optional[Any] = None
_chrome_process: Optional[subprocess.Popen] = None
CDP_PORT = 9222

def ensure_persistent_browser(headless: bool = False) -> str:
    """
    Ensures a single dedicated Chrome browser process is running in the background with CDP enabled.
    Keeps one browser open across multiple script runs instead of opening/closing multiple windows.
    """
    global _chrome_process
    cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    
    # Check if already running and responding
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1) as resp:
            if resp.status == 200:
                return cdp_url
    except Exception:
        pass

    user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "user_data", "browser_use_chrome_session"))
    os.makedirs(user_data_dir, exist_ok=True)

    # Detect Chrome executable
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        import shutil
        chrome_path = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"

    launch_args = [
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--disable-extensions",
        "--disable-component-update",
        "--blink-settings=imagesEnabled=false",  # Speed up DOM rendering 3x by disabling unnecessary images
    ]
    if headless:
        launch_args.append("--headless=new")

    print(f"[browser-use] Launching persistent Chrome instance on port {CDP_PORT}...")
    _chrome_process = subprocess.Popen(launch_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for CDP endpoint to be ready
    import time
    for _ in range(15):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1) as resp:
                if resp.status == 200:
                    print(f"[browser-use] Connected to persistent Chrome instance at {cdp_url}")
                    return cdp_url
        except Exception:
            continue

    return cdp_url


def preflight_check_job_url(url: str) -> tuple[str, bool, Optional[str]]:
    """
    Ultra-fast pre-flight HTTP check:
    1. Follows redirects to uncover direct ATS destinations (Ashby, Greenhouse, Lever).
    2. Probes whether the job is closed or not found without launching a browser.
    Returns: (resolved_url, is_active, reason_if_inactive)
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            final_url = response.geturl()
            status_code = response.getcode()
            if status_code in (404, 410):
                return final_url, False, "Job posting not found (HTTP 404/410)"
            
            # Read first 16KB of HTML to check for expired indicators
            sample_content = response.read(16384).decode("utf-8", errors="ignore").lower()
            closed_markers = [
                "job not found", "posting is no longer available",
                "this job is no longer available", "this job has expired",
                "this position has been filled", "job closed"
            ]
            for marker in closed_markers:
                if marker in sample_content:
                    return final_url, False, f"Job has expired or been taken down ('{marker}')"

            return final_url, True, None
    except urllib.error.HTTPError as he:
        if he.code in (404, 410):
            return url, False, f"Job URL returned HTTP {he.code}"
        return url, True, None
    except Exception:
        # Fallback to navigating with agent if pre-flight times out or is blocked
        return url, True, None


def get_or_create_browser_session(headless: bool = False):
    """
    Maintains a single persistent browser instance across multiple runs by connecting to
    the shared Chrome daemon via CDP so subsequent jobs run in the same browser window.
    Applies aggressive low-latency timings to eliminate idle waiting between actions.
    """
    from browser_use import BrowserSession
    cdp_url = ensure_persistent_browser(headless=headless)
    return BrowserSession(
        cdp_url=cdp_url,
        minimum_wait_page_load_time=0.1,             # Cut from 0.25s to 0.1s
        wait_for_network_idle_page_load_time=0.15,   # Cut from 0.5s to 0.15s (network idle cutoff)
        wait_between_actions=0.02,                   # Instantaneous action execution
        highlight_elements=False,                    # Disable DOM bounding box calculation overhead
        auto_download_pdfs=False,
    )


async def run_browser_use_autofill(
    job_url: str,
    resume_data: Dict[str, Any],
    resume_pdf_path: Optional[str] = None,
    headless: bool = False,
    model_name: Optional[str] = "gemini-3.5-flash-lite",
    custom_api_key: Optional[str] = None,
    auto_submit: bool = False,
    max_steps: int = 50
) -> Dict[str, Any]:
    """
    Runs an autonomous application filling session using browser-use and Gemini.
    DISABLE_GUARDRAILS (module-level flag or BROWSER_USE_DISABLE_GUARDRAILS env var)
    takes precedence over the per-call auto_submit argument.
    """
    # Module-level flag overrides the per-call argument
    effective_auto_submit = DISABLE_GUARDRAILS or auto_submit
    if DISABLE_GUARDRAILS and not auto_submit:
        print("[browser-use] ⚠️  DISABLE_GUARDRAILS=True — overriding auto_submit to True. Application WILL be submitted.")

    try:
        llm = get_browser_use_llm(model_name=model_name, custom_api_key=custom_api_key)
    except Exception as e:
        print(f"[browser-use] Model '{model_name}' fallback triggered: {e}")
        llm = get_browser_use_llm(model_name="gemini-3.5-flash-lite", custom_api_key=custom_api_key)

    # 1. Pre-flight check: resolve redirects (e.g. LinkedIn -> Ashby) and check for expired job
    resolved_url, is_active, inactive_reason = await asyncio.to_thread(preflight_check_job_url, job_url)
    if not is_active:
        print(f"[browser-use] ⚡ Pre-flight detected closed job without browser ({inactive_reason}). Terminating early.")
        return {
            "status": "failed",
            "job_url": job_url,
            "resolved_url": resolved_url,
            "auto_submit": effective_auto_submit,
            "guardrails_disabled": DISABLE_GUARDRAILS,
            "model_used": "preflight-check",
            "steps_taken": 0,
            "is_done": True,
            "final_result": f"Job unavailable: {inactive_reason}",
        }

    target_url = resolved_url or job_url
    if target_url != job_url:
        print(f"[browser-use] 🎯 Resolved direct ATS application URL: {target_url}")

    task_prompt = build_application_task_prompt(
        job_url=target_url,
        resume_data=resume_data,
        resume_pdf_path=resume_pdf_path,
        auto_submit=effective_auto_submit
    )

    browser_session = get_or_create_browser_session(headless=headless)

    available_paths = [os.path.abspath(resume_pdf_path)] if resume_pdf_path and os.path.exists(resume_pdf_path) else []

    mode_str = "AUTO-SUBMIT (GUARDRAILS DISABLED)" if effective_auto_submit else "REVIEW ONLY (GUARDRAIL ACTIVE)"

    # --- Phase 1: Fast Pure-DOM Mode (use_vision=False) ---
    print(f"[browser-use] ⚡ Starting fast pure-DOM autofill ({mode_str}) for {job_url} [vision=False]...")
    agent_fast = Agent(
        task=task_prompt,
        llm=llm,
        browser_session=browser_session,
        available_file_paths=available_paths,
        use_vision=False,
        use_judge=False,
        use_thinking=False,
        max_history_items=5,
        max_actions_per_step=15,
        flash_mode=True,
        enable_planning=False,
        max_failures=2,
        retry_delay=1,
    )

    history = await agent_fast.run(max_steps=max_steps)
    is_done = history.is_done() if hasattr(history, "is_done") else True
    final_res = str(history.final_result() if hasattr(history, "final_result") else "")

    # Determine if the pure-DOM pass succeeded or got stuck
    # If not done or explicitly stated failure/unable to interact, fallback to vision
    failure_indicators = ["unable", "could not find", "cannot find", "failed", "error", "not found"]
    needs_vision_fallback = not is_done or any(ind in final_res.lower() for ind in ["unable to fill", "cannot locate", "stuck", "element not found"])

    if needs_vision_fallback:
        print(f"[browser-use] 👁️ Pure-DOM pass encountered difficulties. Activating Vision + Reasoning (thinking=True) fallback...")
        agent_vision = Agent(
            task=task_prompt + "\nNOTE: Retrying with visual sight and deep reasoning enabled. Analyze the visual layout carefully to locate, solve, and fill any inputs, custom dropdowns, or multi-step modals that were missed.",
            llm=llm,
            browser_session=browser_session,
            available_file_paths=available_paths,
            use_vision=True,
            vision_detail_level="low",
            use_judge=False,
            use_thinking=True,      # Deliberate and reason through tricky/stuck states
            max_history_items=8,
            max_actions_per_step=10,
            flash_mode=False,       # Full reasoning capabilities for fallback
            enable_planning=True,   # Plan around obstacles (modals, captchas, multi-page flows)
            max_failures=2,
            retry_delay=1,
        )
        history = await agent_vision.run(max_steps=max_steps)

    return {
        "status": "success",
        "job_url": job_url,
        "auto_submit": effective_auto_submit,
        "guardrails_disabled": DISABLE_GUARDRAILS,
        "model_used": getattr(llm, "model", model_name),
        "steps_taken": len(history.history) if hasattr(history, "history") else 0,
        "is_done": history.is_done() if hasattr(history, "is_done") else True,
        "final_result": history.final_result() if hasattr(history, "final_result") else "Completed application autofill run.",
    }


if __name__ == "__main__":
    import sys

    # Dynamically load profile from candidate_profile.json
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "candidate_profile.json"))
    candidate_profile = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cand = cfg.get("candidate", {})
                candidate_profile = {
                    "name": cand.get("name", "Akhil Baja"),
                    "email": cand.get("email", "akhilbaja.work@gmail.com"),
                    "phone": cand.get("phone", "+91 9948083135"),
                    "location": cand.get("location", "London, UK"),
                    "linkedin": cand.get("linkedin", "https://linkedin.com/in/akhilbaja"),
                    "github": cand.get("github", "https://github.com/AkhilBaja3005"),
                    "summary": cand.get("experience_summary", ""),
                    "gender": cand.get("gender", "Male"),
                    "citizenship": cand.get("citizenship", "Indian"),
                    "work_authorization": cand.get("work_authorization", "Authorized to work in the UK"),
                    "requires_sponsorship": cand.get("requires_sponsorship", False),
                    "skills": cand.get("core_skills", []),
                    "education": cand.get("education", []),
                    "work_experience": cand.get("work_experience", []),
                }
        except Exception as e:
            print(f"Error loading candidate_profile.json: {e}")

    # Fallback to minimal dict if file load failed
    if not candidate_profile:
        candidate_profile = {
            "name": "Akhil Baja",
            "email": "akhilbaja.work@gmail.com",
            "phone": "+91 9948083135",
            "location": "London, UK",
            "linkedin": "https://linkedin.com/in/akhilbaja",
            "github": "https://github.com/AkhilBaja3005",
            "requires_sponsorship": True
        }

    # Quick standalone CLI prototype runner
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://boards.greenhouse.io"
    resume_pdf = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "applications_tracker", "tailored_resumes", "master_resume.pdf"))
    resume_path = resume_pdf if os.path.exists(resume_pdf) else None

    print(f"Testing browser-use prototype on: {test_url}")
    print(f"Loaded profile for: {candidate_profile.get('name')} ({candidate_profile.get('email')})")
    result = asyncio.run(run_browser_use_autofill(test_url, candidate_profile, resume_pdf_path=resume_path, max_steps=25))
    print("Result:", json.dumps(result, indent=2))

