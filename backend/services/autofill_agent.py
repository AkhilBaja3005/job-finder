import os
import json
import re
import asyncio
from typing import Optional

from services.gemini_client import generate_content_with_fallback


def _safe_user_data_key(token: Optional[str]) -> str:
    """Mirrors main.py's _safe_key(): turns a token (or 'guest') into a
    filesystem-safe key with no path separators, so each user/guest gets an
    isolated Playwright browser profile directory instead of sharing one."""
    key = token or "guest"
    key = re.sub(r'[^a-zA-Z0-9_-]', '', key)[:40]
    return key or "guest"

def get_answer_from_llm(question: str, field_context: str, resume_data: dict, custom_api_key: Optional[str] = None) -> str:
    """
    Uses the app's multi-provider LLM client to answer a custom application question.
    Receives both the field's visual text context (HTML/Surrounding text) and the candidate's resume data
    to form an exact answer.

    Routes through generate_content_with_fallback (the same client used everywhere
    else in the app) rather than a hardcoded Gemini client, so a user's own
    Gemini/Claude/Groq/OpenRouter key (threaded down from /apply's active_api_key)
    is actually honored here instead of being silently ignored in favor of
    whatever GEMINI_API_KEY happens to be set on the server.
    """
    prompt = f"""
    You are an AI assistant helping a candidate fill out a job application. Answer this specific application question accurately based on the candidate's resume and the provided page context.

    Resume details:
    {json.dumps(resume_data, indent=2)}

    Application Field Context (HTML / Surrounding text of the question/dropdown):
    ---
    {field_context}
    ---

    Application Question:
    "{question}"

    Instructions:
    - Provide a direct, concise answer.
    - If it's a dropdown/select option, provide the exact text matching one of the options shown in the context.
    - If it's a yes/no question, respond with exactly 'Yes' or 'No'.
    - If it asks for years of experience, respond with a single integer (e.g., '3').
    - Respond with ONLY the answer text — no explanations, no markdown, no quotes.
    """
    try:
        return generate_content_with_fallback(prompt, response_schema=None, custom_api_key=custom_api_key).strip()
    except Exception as e:
        print(f"Error calling LLM for question: {e}")
        return ""

async def fill_visible_fields(page, resume_data: dict, resume_pdf_path: str, session_filled_questions: set, custom_api_key: Optional[str] = None):
    """
    Scans the current page state, finds all visible, unfilled inputs,
    and populates them dynamically. Uses session_filled_questions to prevent
    re-filling fields if the page dynamically refreshes or reloads.
    """
    # Find all inputs, textareas, and select elements
    inputs = await page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select")

    for inp in inputs:
        try:
            # Check if element is visible and not already handled
            is_visible = await inp.is_visible()
            already_filled = await inp.get_attribute("data-autofilled")

            if not is_visible or already_filled == "true":
                continue

            inp_type = await inp.get_attribute("type") or ""
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""

            # Get associated label text
            label_text = ""
            if inp_id:
                label = await page.query_selector(f"label[for='{inp_id}']")
                if label:
                    label_text = await label.inner_text()

            # Extract surrounding parent container HTML for context
            parent_html = ""
            parent = await inp.evaluate_handle("el => el.closest('div')")
            if parent:
                parent_html = await page.evaluate("el => el.outerHTML", parent)
                if not label_text:
                    label_text = await page.evaluate("el => el.innerText", parent)

            field_key = (inp_name + " " + label_text + " " + inp_id).lower().strip()
            if not field_key:
                continue

            question_text = label_text.split('\n')[0].strip() if label_text else inp_name

            # 1. Skip if this question has already been answered during this application run
            if question_text in session_filled_questions:
                # Mark it in the DOM just to keep current session tidy
                await inp.evaluate("el => el.setAttribute('data-autofilled', 'true')")
                continue

            # 2. Resume PDF upload
            if inp_type == "file":
                placeholder = await inp.get_attribute("placeholder") or ""
                if "resume" in inp_name.lower() or "cv" in inp_name.lower() or "resume" in placeholder.lower():
                    await inp.set_input_files(resume_pdf_path)
                    await inp.evaluate("el => el.setAttribute('data-autofilled', 'true')")
                    session_filled_questions.add(question_text)
                    print(f"Uploaded tailored resume PDF: {resume_pdf_path}")
                    continue

            # Heuristic matching for common personal fields
            if "first name" in field_key or "firstname" in field_key:
                name = resume_data.get("name", "John")
                first_name = name.split()[0] if name and isinstance(name, str) else "John"
                await inp.fill(first_name)
                session_filled_questions.add(question_text)
            elif "last name" in field_key or "lastname" in field_key:
                name = resume_data.get("name", "Doe")
                names = name.split() if name and isinstance(name, str) else ["Doe"]
                last_name = names[-1] if len(names) > 0 else "Doe"
                await inp.fill(last_name)
                session_filled_questions.add(question_text)
            elif "email" in field_key:
                await inp.fill(resume_data.get("email", ""))
                session_filled_questions.add(question_text)
            elif "phone" in field_key or "mobile" in field_key:
                await inp.fill(resume_data.get("phone", ""))
                session_filled_questions.add(question_text)
            elif "linkedin" in field_key and len(resume_data.get("links", [])) > 0:
                li_url = next((link for link in resume_data["links"] if "linkedin" in link), "")
                if li_url:
                    await inp.fill(li_url)
                    session_filled_questions.add(question_text)
            elif "github" in field_key and len(resume_data.get("links", [])) > 0:
                gh_url = next((link for link in resume_data["links"] if "github" in link), "")
                if gh_url:
                    await inp.fill(gh_url)
                    session_filled_questions.add(question_text)
            else:
                # LLM-based answering for custom questions with page context
                if question_text and len(question_text) > 3:
                    print(f"Asking LLM to answer: '{question_text}' with visual HTML context...")
                    answer = await asyncio.to_thread(get_answer_from_llm, question_text, parent_html, resume_data, custom_api_key)
                    if answer:
                        print(f"LLM Answer: {answer}")
                        if inp_type == "checkbox":
                            if "yes" in answer.lower() or "true" in answer.lower():
                                await inp.check()
                        elif await inp.evaluate("el => el.tagName") == "SELECT":
                            options = await inp.query_selector_all("option")
                            for opt in options:
                                val = await opt.get_attribute("value") or ""
                                text = await opt.inner_text() or ""
                                if answer.lower() in val.lower() or answer.lower() in text.lower():
                                    await inp.select_option(value=val)
                                    break
                        else:
                            await inp.fill(answer)

                    # Mark as successfully handled in this run
                    session_filled_questions.add(question_text)

            # Mark as filled in the DOM
            await inp.evaluate("el => el.setAttribute('data-autofilled', 'true')")

        except Exception as e:
            print(f"Skipping input field due to error: {e}")

async def autofill_job_application(url: str, resume_data: dict, resume_pdf_path: str, interactive_mode: bool = True, user_token: Optional[str] = None, custom_api_key: Optional[str] = None):
    """
    Launches a headed browser with a persistent user data directory (keeping you logged in).
    Continuously monitors the application page, dynamically filling out forms step-by-step.

    The browser profile is scoped per-user (via user_token) rather than a single shared
    "./user_data" directory, so one user's/guest's login cookies for job sites (LinkedIn,
    Indeed, Greenhouse/Lever portals, etc.) can't leak into another user's autofill session.
    """
    # pyrefly: ignore [missing-import]
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        user_data_dir = os.path.abspath(f"./user_data/{_safe_user_data_key(user_token)}")

        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print(f"Navigating to: {url}")
        await page.goto(url)

        print("Autofill Agent active. Monitoring application forms dynamically...")

        # State tracker that survives DOM refreshes/AJAX reloads
        session_filled_questions = set()

        try:
            while not page.is_closed():
                await fill_visible_fields(page, resume_data, resume_pdf_path, session_filled_questions, custom_api_key)

                if not interactive_mode:
                    next_btn = await page.query_selector("button:has-text('Next'), button:has-text('Continue'), button:has-text('Review')")
                    if next_btn and await next_btn.is_visible():
                        print("Clicking Next/Continue button automatically...")
                        await next_btn.click()
                        await page.wait_for_timeout(2000)

                await asyncio.sleep(2)

        except Exception as e:
            print(f"Autofill event loop error or browser closed: {e}")
        finally:
            if not interactive_mode:
                await context.close()
