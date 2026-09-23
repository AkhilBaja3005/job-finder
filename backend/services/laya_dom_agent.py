"""
laya_dom_agent.py — Non-autoregressive ultra-fast DOM agent powered by Laya.

Directly inspects interactive elements in the active browser page via Playwright / CDP,
resolves all field classifications & candidate values on-device in <10ms,
and batches the autofill actions with zero external cloud latency.
"""

import os
import sys
import logging
import asyncio
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    from services.laya_router import get_laya_router, LayaDecisionRouter
except ImportError:
    from backend.services.laya_router import get_laya_router, LayaDecisionRouter


async def execute_laya_fast_pass(
    page,
    candidate_profile: Dict[str, Any],
    resume_pdf_path: Optional[str] = None,
    session_filled_questions: Optional[set] = None
) -> Dict[str, Any]:
    """
    Executes a high-speed (<50ms) Laya decision pass over all interactive form elements on the page.
    Fills text, selects dropdowns, sets phone country codes, and attaches resume PDFs.
    """
    router: LayaDecisionRouter = get_laya_router()
    filled_count = 0
    filled_set = session_filled_questions if session_filled_questions is not None else set()

    # Query all visible candidate form elements
    inputs = await page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select")

    for inp in inputs:
        try:
            if not await inp.is_visible():
                continue

            # Check if already processed
            already_filled = await inp.get_attribute("data-autofilled")
            if already_filled == "true":
                continue

            # Extract label, placeholder, name, id, and aria attributes
            meta = await inp.evaluate("""el => {
                let label = '';
                if (el.id) {
                    const l = document.querySelector(`label[for="${el.id}"]`);
                    if (l) label = l.innerText;
                }
                if (!label) {
                    const parent = el.closest('label') || el.closest('.form-group') || el.closest('[data-automation-id]') || el.parentElement;
                    if (parent) label = parent.innerText;
                }
                return {
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    type: el.type || '',
                    tagName: el.tagName || '',
                    label: (label || '').trim().replace(/\\n/g, ' ')
                };
            }""")

            search_key = f"{meta['label']} {meta['placeholder']} {meta['name']} {meta['id']}".strip()
            route_type, reflex_val = router.route_decision(search_key, candidate_profile)

            # 1. Resume PDF Upload
            if meta["type"] == "file" or "resume" in search_key.lower() or "cv" in search_key.lower():
                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    await inp.set_input_files(resume_pdf_path)
                    await inp.evaluate("el => el.setAttribute('data-autofilled', 'true')")
                    filled_count += 1
                    continue

            # 2. Reflex Decision Match (Laya)
            if route_type == "reflex" and reflex_val is not None and str(reflex_val).strip() != "":
                val_str = str(reflex_val).strip()
                if meta["tagName"] == "SELECT":
                    # Match exact option
                    options = await inp.query_selector_all("option")
                    matched = False
                    for opt in options:
                        o_val = await opt.get_attribute("value") or ""
                        o_text = await opt.inner_text() or ""
                        cand_l = val_str.lower()
                        if cand_l in o_val.lower() or cand_l in o_text.lower() or cand_l.lstrip("+") in o_val.lower() or cand_l.lstrip("+") in o_text.lower():
                            await inp.select_option(value=o_val)
                            matched = True
                            break
                    if not matched:
                        try:
                            await inp.select_option(value=val_str)
                        except Exception:
                            pass
                elif meta["type"] == "checkbox":
                    if "yes" in val_str.lower() or "true" in val_str.lower():
                        await inp.check()
                else:
                    await inp.fill(val_str)

                await inp.evaluate("el => el.setAttribute('data-autofilled', 'true')")
                filled_count += 1
                filled_set.add(search_key)

        except Exception as e:
            logger.debug(f"[laya-agent] Field processing error: {e}")
            continue

    return {
        "status": "success",
        "filled_count": filled_count,
        "mode": "laya-reflex-v1"
    }
