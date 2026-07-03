import os
import json
import asyncio
import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright
from services.gemini_client import generate_content_with_fallback

# ─── Pydantic Schemas for Structured Actions ───────────────────────────────

class AgentAction(BaseModel):
    action_type: Literal["fill", "select", "click", "upload", "pause", "complete"] = Field(
        description="The type of action to perform. "
                    "'fill': enter text into an input field. "
                    "'select': pick an option from a dropdown. "
                    "'click': click a button or link. "
                    "'upload': upload the resume PDF. "
                    "'pause': stop and wait for manual human interaction. "
                    "'complete': finish the application."
    )
    locator_label: Optional[str] = Field(
        default=None,
        description="The text label, placeholder, aria-label, role name, or visible text of the target element."
    )
    value: Optional[str] = Field(
        default=None,
        description="The value to enter (for 'fill') or the option to pick (for 'select')."
    )
    reason: Optional[str] = Field(
        default=None,
        description="The reason for pausing (only for 'pause' action type)."
    )

class NextStepDecision(BaseModel):
    thought: str = Field(
        description="Reasoning about the current page state, what fields are visible, what needs to be filled, and what actions to take."
    )
    actions: List[AgentAction] = Field(
        description="Ordered list of actions to execute sequentially on the current page."
    )

# ─── Accessibility Tree Extraction & Flattening ──────────────────────────────

def _flatten_accessibility_tree(node: dict, indent: int = 0) -> List[str]:
    """
    Recursively flattens the Playwright accessibility tree snapshot into a clean list
    of readable semantic elements, omitting layout nodes to save context window tokens.
    """
    lines = []
    role = node.get("role", "")
    name = node.get("name", "").strip()
    value = node.get("value", "")
    description = node.get("description", "")
    
    # Filter out pure layout or structural wrapper roles unless they contain useful text/names
    skip_roles = {"generic", "List", "ListItem", "Grid", "Row", "Cell", "WebArea"}
    
    label_info = []
    if name:
        label_info.append(f'name: "{name}"')
    if value:
        label_info.append(f'value: "{value}"')
    if description:
        label_info.append(f'desc: "{description}"')
        
    for prop in ["required", "disabled", "checked", "expanded", "focused"]:
        if node.get(prop):
            label_info.append(prop)

    # Format the element if it has a role or label info
    if role and (label_info or role not in skip_roles):
        info_str = ", ".join(label_info)
        space = "  " * indent
        lines.append(f"{space}[{role}] {info_str if info_str else '(no label)'}")

    # Process children
    for child in node.get("children", []):
        lines.extend(_flatten_accessibility_tree(child, indent + 1))
        
    return lines

async def get_accessibility_context(page) -> str:
    """
    Extracts a clean, semantic text map of all interactive form elements across all frames.
    Supports iframes and nested portal elements dynamically.
    """
    js_extractor = """
    () => {
        let root = document;
        let activeModal = document.querySelector("div[role='dialog'], [role='dialog'], .aria-modal, #artdeco-modal-outlet, .jobs-easy-apply-modal");
        if (activeModal && activeModal.offsetWidth > 0 && activeModal.offsetHeight > 0) {
            root = activeModal;
        }

        let lines = [];
        let elements = root.querySelectorAll("input, select, textarea, button, h1, h2, h3, [role='textbox'], [role='checkbox'], [role='button']");
        
        elements.forEach(el => {
            if (el.offsetWidth === 0 || el.offsetHeight === 0 || el.type === 'hidden') {
                return;
            }
            
            let tag = el.tagName.toLowerCase();
            let role = el.getAttribute("role") || tag;
            let type = el.getAttribute("type") || "";
            
            let label = "";
            let id = el.getAttribute("id");
            if (id) {
                let lblEl = document.querySelector(`label[for="${id}"]`);
                if (lblEl) label = lblEl.innerText.trim();
            }
            
            if (!label) {
                label = el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("name") || "";
            }
            
            if (!label && tag === 'button') {
                label = el.innerText.trim();
            }
            
            if (!label) {
                let parent = el.closest('div');
                if (parent) {
                    label = parent.innerText.split('\\n')[0].trim();
                }
            }

            label = label.replace(/\\s+/g, ' ').trim();
            let val = el.value || el.innerText || "";
            if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
                val = el.checked ? "checked" : "unchecked";
            }
            
            let required = el.hasAttribute("required") || el.getAttribute("aria-required") === "true" ? "required" : "";
            
            if (tag === 'h1' || tag === 'h2' || tag === 'h3') {
                lines.push(`[heading] name: "${el.innerText.trim()}"`);
            } else {
                lines.push(`[${role}${type ? ':' + type : ''}] name: "${label}", value: "${val}"${required ? ', ' + required : ''}`);
            }
        });
        
        return lines.join("\\n");
    }
    """
    try:
        results = []
        for frame in page.frames:
            try:
                # Verify frame is still attached and active
                if frame.is_detached():
                    continue
                context_str = await frame.evaluate(js_extractor)
                if context_str and context_str.strip() and context_str != "No visible form elements found.":
                    results.append(context_str)
            except Exception:
                # Ignore cross-origin access blocks silently
                pass

        if not results:
            return "No visible form elements found."
            
        final_context = "\n".join(results)
        
        # Print a clean, formatted snapshot debug log
        print("=== [DEBUG ACCESSIBILITY] EXTRACTED FORM STATE ===")
        print(final_context)
        print("==================================================")
        return final_context
    except Exception as e:
        print(f"[DEBUG ACCESSIBILITY] Captured error: {str(e)}")
        return f"Error extracting page state: {str(e)}"

# ─── Playwright Locator Helper ──────────────────────────────────────────────

async def locate_element(page, label: str, action_type: str):
    """
    Resolves the best semantic locator for a given action and element descriptor.
    Searches sequentially through the main frame and all active sub-frames.
    """
    clean_label = label.strip()
    if not clean_label:
        return None
        
    # Check main page first, then all active frames
    containers = [page]
    try:
        containers.extend([f for f in page.frames if not f.is_detached() and f != page])
    except Exception:
        pass
        
    for container in containers:
        try:
            # 1. Try finding elements using Playwright's get_by_label
            el = container.get_by_label(clean_label, exact=False)
            if await el.count() > 0:
                for i in range(await el.count()):
                    candidate = el.nth(i)
                    if await candidate.is_visible():
                        return candidate

            # 2. Try get_by_placeholder
            el = container.get_by_placeholder(clean_label, exact=False)
            if await el.count() > 0:
                for i in range(await el.count()):
                    candidate = el.nth(i)
                    if await candidate.is_visible():
                        return candidate

            # 3. Try get_by_role (especially for buttons and comboboxes)
            role_map = {
                "click": ["button", "link"],
                "fill": ["textbox", "searchbox"],
                "select": ["combobox", "listbox"],
                "upload": ["button", "textbox"]
            }
            roles = role_map.get(action_type, ["textbox"])
            for r in roles:
                try:
                    el = container.get_by_role(r, name=clean_label, exact=False)
                    if await el.count() > 0:
                        for i in range(await el.count()):
                            candidate = el.nth(i)
                            if await candidate.is_visible():
                                return candidate
                except Exception:
                    pass

            # 4. Try get_by_text
            el = container.get_by_text(clean_label, exact=False)
            if await el.count() > 0:
                for i in range(await el.count()):
                    candidate = el.nth(i)
                    if await candidate.is_visible():
                        return candidate

            # 5. Tag selector backups
            selectors = [
                f"input[placeholder*='{clean_label}']",
                f"input[name*='{clean_label}']",
                f"button:has-text('{clean_label}')",
                f"a:has-text('{clean_label}')"
            ]
            for sel in selectors:
                try:
                    el = container.locator(sel)
                    if await el.count() > 0:
                        for i in range(await el.count()):
                            candidate = el.nth(i)
                            if await candidate.is_visible():
                                return candidate
                except Exception:
                    pass
        except Exception:
            pass

    return None

# ─── Execute Actions ────────────────────────────────────────────────────────

async def execute_agent_action(page, action: AgentAction, resume_pdf_path: str) -> bool:
    """Executes a single structured AgentAction using Playwright locators."""
    action_type = action.action_type
    label = action.locator_label or ""
    val = action.value or ""
    
    print(f"[Autofill Action] Executing: {action_type.upper()} | Label: '{label}' | Value: '{val}'")
    
    if action_type == "pause":
        print(f"[Autofill Action] PAUSING loop: {action.reason or 'User requested pause'}")
        return False
        
    if action_type == "complete":
        print("[Autofill Action] COMPLETE action reached.")
        return True

    # Locate the target element
    el = await locate_element(page, label, action_type)
    if not el:
        print(f"[Autofill Action] WARNING: Could not find element matching '{label}' for action '{action_type}'")
        return False

    try:
        # Focus element to trigger dynamic JS focus events
        await el.focus()
        
        if action_type == "fill":
            await el.fill(val)
        elif action_type == "select":
            # For select option, try direct selection or picking by value/text
            try:
                await el.select_option(label=val)
            except Exception:
                try:
                    await el.select_option(value=val)
                except Exception:
                    # Fallback: type value to auto-select option
                    await el.type(val)
        elif action_type == "click":
            try:
                # Try standard Playwright click first (with 3s timeout)
                await el.click(timeout=3000)
            except Exception as click_err:
                print(f"[Autofill Action] Standard click intercepted or timed out: {str(click_err)[:100]} | Retrying via DOM trigger...")
                # Dispatch DOM click bypassing physical cursor layout hit-testing
                await el.evaluate("el => el.click()")
        elif action_type == "upload":
            # If the element is a button/input wrapper, resolve the actual file input underneath
            if await el.evaluate("el => el.tagName") != "INPUT":
                # Find input type=file inside or near the element
                file_input = page.locator("input[type='file']")
                if await file_input.count() > 0:
                    await file_input.first.set_input_files(resume_pdf_path)
                    print(f"[Autofill Action] Uploaded resume to underlying file input: {resume_pdf_path}")
                else:
                    raise Exception("File input tag not found under locator.")
            else:
                await el.set_input_files(resume_pdf_path)
            
        # Give pages a brief moment to update state or run event handlers
        await page.wait_for_timeout(350)
        return True
    except Exception as e:
        print(f"[Autofill Action] ERROR executing action on '{label}': {str(e)}")
        return False

# ─── Thought Phase ──────────────────────────────────────────────────────────

async def get_next_actions_from_llm(
    current_url: str,
    accessibility_tree: str,
    resume_data: dict,
    job_description: str,
    custom_api_key: Optional[str] = None
) -> NextStepDecision:
    """Queries Gemini to evaluate page state and return structured actions."""
    
    prompt = f"""You are an advanced job application autofill agent using Playwright.
Analyze the current page state, candidate profile, and job details below. Decide on the next set of actions to perform on the page.

CURRENT APPLICATION URL:
{current_url}

CANDIDATE PROFILE (RESUME DATA):
{json.dumps(resume_data, indent=2)}

TARGET JOB DESCRIPTION:
---
{job_description[:1500]}
---

CURRENT PAGE ACCESSIBILITY TREE STATE:
---
{accessibility_tree}
---

INSTRUCTIONS:
1. Map the visible fields (textbox, combobox, checkbox, radio, file input) to the candidate's profile.
2. Generate a list of sequential actions to fill/click items on this current page state.
3. If you encounter file inputs (upload) for the Resume/CV, return an 'upload' action type.
4. When you fill all fields on the current page, include a 'click' action to progress (e.g. clicking 'Next', 'Continue', or 'Save').
5. If you reach the final submission or preview review page (usually has a 'Submit', 'Submit Application', or 'Finish' button), insert a 'pause' action to let the human review before submission.
6. If the page is complete or has successfully completed the submission, return a 'complete' action.
"""

    response_text = generate_content_with_fallback(
        prompt=prompt,
        response_schema=NextStepDecision,
        custom_api_key=custom_api_key
    )
    
    decision_data = json.loads(response_text)
    return NextStepDecision(**decision_data)

# ─── Main Autofill Loop ───────────────────────────────────────────────────────

async def autofill_job_application(
    url: str,
    resume_data: dict,
    resume_pdf_path: str,
    custom_api_key: Optional[str] = None,
    interactive_mode: bool = True
):
    """
    Launches browser context with persistent state, runs the dynamic Observation-Thought-Action loop,
    and fills out application forms step-by-step using Accessibility Tree snapshots.
    """
    async with async_playwright() as p:
        user_data_dir = os.path.abspath("./user_data")
        
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        print(f"[Autofill Agent] Navigating to: {url}")
        await page.goto(url)
        
        # Initial sleep to let dynamic content or sign-in state settle
        await page.wait_for_timeout(3000)
        
        # Automatically detect and click the Easy Apply button to open the popup form
        try:
            easy_apply_btn = page.locator("button.jobs-apply-button")
            if await easy_apply_btn.count() > 0 and await easy_apply_btn.first.is_visible():
                print("[Autofill Agent] 'Easy Apply' button found. Clicking it to launch form popup...")
                await easy_apply_btn.first.click()
                # Wait for modal overlay to slide in
                await page.wait_for_timeout(2000)
            else:
                print("[Autofill Agent] 'Easy Apply' button not found on load. Let's see if modal is already open.")
        except Exception as e:
            print(f"[Autofill Agent] Note: Checked for Easy Apply button but encountered: {str(e)}")

        # Keep track of recently attempted actions to prevent infinite loop errors
        action_history = []
        
        try:
            while not page.is_closed():
                # 1. Observation Phase
                print("[Autofill Agent] Capturing Accessibility Tree state...")
                tree = await get_accessibility_context(page)
                
                # 2. Thought Phase
                print("[Autofill Agent] Consulting Gemini for next steps...")
                decision = await get_next_actions_from_llm(
                    current_url=page.url,
                    accessibility_tree=tree,
                    resume_data=resume_data,
                    job_description=resume_data.get("summary", ""), # Fallback to summary if JD not provided
                    custom_api_key=custom_api_key
                )
                
                print(f"[Autofill Agent] Reasoning: {decision.thought}")
                
                if not decision.actions:
                    print("[Autofill Agent] No actions returned. Sleeping and retrying...")
                    await asyncio.sleep(3)
                    continue
                
                # Check for infinite action loops (e.g. repeated failure clicks)
                current_actions_summary = [(a.action_type, a.locator_label) for a in decision.actions]
                if len(action_history) > 3 and action_history[-1] == current_actions_summary:
                    print("[Autofill Agent] Infinite loop detected on the same set of actions. Pausing for human intervention...")
                    # Insert manual sleep to let user fix
                    await asyncio.sleep(5)
                    continue
                
                action_history.append(current_actions_summary)
                if len(action_history) > 10:
                    action_history.pop(0)

                # 3. Action Phase
                paused = False
                pause_reason = ""
                completed = False
                for action in decision.actions:
                    if action.action_type == "pause":
                        paused = True
                        pause_reason = action.reason or "Needs manual interaction"
                        break
                    if action.action_type == "complete":
                        completed = True
                        break
                        
                    success = await execute_agent_action(page, action, resume_pdf_path)
                    if not success:
                        # Stop execution chain on failure to re-evaluate page state
                        break
                
                if completed:
                    print("[Autofill Agent] Success! Application flow finished.")
                    break
                    
                if paused:
                    print(f"[Autofill Agent] Human-in-the-Loop active: {pause_reason}")
                    print("[Autofill Agent] Waiting 5 seconds for user action before checking page state again...")
                    await asyncio.sleep(5)
                    # Loop continues, will capture a new Accessibility Tree on next iteration
                    continue
                
                # Yield execution thread briefly
                await asyncio.sleep(2.5)
                
        except Exception as e:
            print(f"[Autofill Agent] Loop error or page closed: {e}")
        finally:
            if not interactive_mode:
                await context.close()
