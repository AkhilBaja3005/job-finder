"""
browser_use_agent.py — Autonomous Job Application Autofill using browser-use & Gemini Flash / Flash-Lite.

Uses browser-use to navigate multi-step job application portals (Ashby, Greenhouse, Lever, Workday),
inspect visual DOM structures, auto-populate candidate details, upload resumes, and answer screening questions.
"""

import os
import sys
import json
import asyncio
from typing import Optional, Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use import Agent, Browser, ChatGoogle
from config.constants import DEFAULT_FAST_LITE_MODELS, PREFERRED_GEMINI_MODEL


def get_browser_use_llm(model_name: Optional[str] = None, custom_api_key: Optional[str] = None):
    """
    Initializes browser-use native ChatGoogle client targeting Gemini Flash-Lite / Flash.
    """
    api_key = custom_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for browser-use agent execution.")

    target_model = model_name or os.getenv("BROWSER_USE_MODEL", "gemini-2.5-flash")
    
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

    task = f"""
    Navigate to the job application URL: {job_url}
    
    You are an expert AI Career Assistant acting on behalf of the applicant to fill out this job application form.
    
    Applicant Profile Details:
    - Full Name: {candidate_name}
    - Email Address: {email}
    - Phone Number: {phone}
    - Current Location: {location}
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
        "5. SUBMIT APPLICATION: Carefully review all completed fields. Once all required inputs, attachments, and questions are satisfied, click the final 'Submit Application' or 'Send Application' button to submit the application completely."
        if auto_submit
        else "5. SAFETY GUARDRAIL: Navigate through intermediate pages ('Next' / 'Continue'), but DO NOT click final 'Submit Application' or 'Send Application'. Stop on the final review/preview step and report a summary of completed fields."
    )

    task += f"""
    Execution Instructions:
    1. Locate the application form on the page. If there is an 'Apply Now' or 'Apply for this job' button, click it.
    2. Carefully fill in standard fields (First Name, Last Name, Email, Phone, LinkedIn, Location).
    3. If there is a file input or drag-and-drop zone for Resume/CV, upload the specified resume file.
    4. For dropdowns and multiple-choice questions (e.g. Work Authorization, Notice Period, Sponsorship, Gender, Race/Ethnicity, Disability, Veteran status):
       - Select the option that best matches the applicant profile details above.
       - Answer truthfully and concisely based on the provided profile.
    {submission_instruction}
    """
    return task


import subprocess
import urllib.request

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


def get_or_create_browser_session(headless: bool = False):
    """
    Maintains a single persistent browser instance across multiple runs by connecting to
    the shared Chrome daemon via CDP so subsequent jobs run in the same browser window.
    """
    from browser_use import BrowserSession
    cdp_url = ensure_persistent_browser(headless=headless)
    return BrowserSession(cdp_url=cdp_url)


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
    """
    try:
        llm = get_browser_use_llm(model_name=model_name, custom_api_key=custom_api_key)
    except Exception as e:
        print(f"[browser-use] Model '{model_name}' fallback triggered: {e}")
        llm = get_browser_use_llm(model_name="gemini-2.5-flash", custom_api_key=custom_api_key)

    task_prompt = build_application_task_prompt(
        job_url=job_url,
        resume_data=resume_data,
        resume_pdf_path=resume_pdf_path,
        auto_submit=auto_submit
    )

    browser_session = get_or_create_browser_session(headless=headless)

    available_paths = [os.path.abspath(resume_pdf_path)] if resume_pdf_path and os.path.exists(resume_pdf_path) else []

    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser_session=browser_session,
        available_file_paths=available_paths,
        use_vision=True,
        max_failures=3,
        retry_delay=2,
    )

    mode_str = "AUTO-SUBMIT" if auto_submit else "REVIEW ONLY (GUARDRAIL)"
    print(f"[browser-use] Starting visible autonomous autofill ({mode_str}) for {job_url} with model {model_name}...")
    history = await agent.run(max_steps=max_steps)

    return {
        "status": "success",
        "job_url": job_url,
        "auto_submit": auto_submit,
        "model_used": getattr(llm, "model", model_name),
        "steps_taken": len(history.history) if hasattr(history, "history") else 0,
        "is_done": history.is_done() if hasattr(history, "is_done") else True,
        "final_result": history.final_result() if hasattr(history, "final_result") else "Completed application autofill run.",
    }


if __name__ == "__main__":
    import sys
    # Quick standalone CLI prototype runner
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://boards.greenhouse.io"
    sample_profile = {
        "name": "Akhil Baja",
        "email": "akhilbaja.work@gmail.com",
        "phone": "+91 9948083135",
        "location": "London, UK",
        "linkedin": "https://linkedin.com/in/akhilbaja",
        "github": "https://github.com/AkhilBaja3005",
        "summary": "AI Systems Engineer specializing in LLMs, distributed systems, and agentic workflows."
    }
    resume_pdf = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "applications_tracker", "tailored_resumes", "master_resume.pdf"))
    resume_path = resume_pdf if os.path.exists(resume_pdf) else None
    print(f"Testing browser-use prototype on: {test_url}")
    result = asyncio.run(run_browser_use_autofill(test_url, sample_profile, resume_pdf_path=resume_path, max_steps=25))
    print("Result:", json.dumps(result, indent=2))
