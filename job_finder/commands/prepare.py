"""
`job-finder prepare`: build the application pack (tailored CV, cover letter if needed, job description, fit analysis)
for approved jobs, one folder each under applications/.

    job-finder prepare                      every approved job that has no pack yet (`approve` already does this)
    job-finder prepare --ids 3,7            these jobs (re-uses your edits to cv.json / cover_letter.txt)
    job-finder prepare --ids 3 --redo       throw the pack away and regenerate it from scratch
    job-finder prepare --ids 3 --render-only   rebuild cv.pdf / cover_letter.pdf from your edited cv.json / cover_letter.txt
    job-finder prepare --cover-letter always|auto|never      (default auto: only when the posting mentions a cover letter)

Any regeneration sets "Docs OK" back to No: you must review the new documents again before `apply` will use them.
"""

import argparse
import asyncio
import os
import re
import sys
from typing import Any, Dict, List, Optional

from job_finder import ui


def _ids(text: Optional[str]):
    return [int(x) for x in re.split(r"[,\s]+", text.strip()) if x] if text else None


def fetch_descriptions(urls: List[str], timeout: float = 45.0) -> Dict[str, str]:
    """Job description text per URL (uses the scraper's cache; blocked pages come back empty)."""
    from backend.services.scraper import scrape_job_description

    async def _all():
        out = {}
        for u in urls:
            try:
                res = await asyncio.wait_for(scrape_job_description(u), timeout=timeout)
                blocked = isinstance(res, dict) and res.get("is_bot_blocked")
                text = (res.get("description") or "").strip() if isinstance(res, dict) and not blocked else ""
                out[u] = text if len(text) >= 100 else ""
            except Exception:
                out[u] = ""
        return out
    return asyncio.run(_all())


def prepare_jobs(rows: List[Dict[str, Any]], scanned, approved, candidate: dict, level: Optional[str] = None,
                 cover_letter: str = "auto", redo: bool = False, render_only: bool = False) -> List[Any]:
    """Build packs for `rows` (approved-workbook rows) and record the result in both workbooks. Returns PackResults."""
    from backend.services import application_pack as ap

    descs = {} if render_only else fetch_descriptions([r["Job URL"] for r in rows if r.get("Job URL")])
    results, updates_a, updates_s = [], [], []
    for r in rows:
        try:
            res = ap.build_pack(r, candidate, descs.get(r.get("Job URL"), ""), level=level, cover_letter=cover_letter,
                                redo=redo, render_only=render_only)
        except Exception as e:                       # one bad job must not stop the rest
            ui.warn(f"#{r.get('ID')} {r.get('Company')}: could not build the pack ({type(e).__name__}: {e})")
            continue
        results.append((r, res))
        note = f"Pack {res.status.lower()}"
        updates_a.append(({"row_id": r.get("ID")},
                          {"Pack Folder": res.folder, "Cover Letter": res.cover_letter, "Docs OK": "No"}, note))
        updates_s.append(({"row_id": r.get("ID")}, {"Pack Folder": res.folder}, None))
    if updates_a:
        approved.update_many(updates_a)
        scanned.update_many(updates_s)
    return results


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services.excel_tracker import ExcelTracker, approved_path

    scanned = ExcelTracker()
    approved = ExcelTracker(approved_path(scanned.path))
    prof = load_profile_data() or {}
    candidate, prefs = prof.get("candidate", {}), prof.get("search_preferences", {})
    ids = _ids(args.ids)

    rows = []
    for r in approved.rows():
        if str(r.get("Applied") or "No") == "Yes" or not r.get("Job URL"):
            continue
        if ids is not None:
            if r.get("ID") in ids:
                rows.append(r)
        elif str(r.get("Status")) == "Approved" and (args.redo or args.render_only or not (r.get("Pack Folder") and os.path.isdir(str(r.get("Pack Folder"))))):
            rows.append(r)
    if not rows:
        ui.info("Nothing to prepare. Approved jobs that already have a pack are skipped; use --ids N (add --redo to regenerate).")
        ui.info("Approve jobs first with `job-finder approve`.")
        return

    print(f"Preparing {len(rows)} application pack(s) ({'re-rendering PDFs' if args.render_only else 'tailoring CV, checking cover letter'})...")
    results = prepare_jobs(rows, scanned, approved, candidate, level=prefs.get("level"), cover_letter=args.cover_letter,
                           redo=args.redo, render_only=args.render_only)
    if not results:
        sys.exit(1)
    table = [[str(r.get("ID")), str(r.get("Company"))[:20], str(r.get("Job Role"))[:30],
              "tailored" if res.cv_tailored else "as-is", res.cover_letter, res.status] for r, res in results]
    ui.print_table("Application packs", ["ID", "Company", "Role", "CV", "Cover letter", "Status"], table, status_col=None)
    for r, res in results:
        for w in res.warnings:
            ui.warn(f"#{r.get('ID')} {r.get('Company')}: {w}")
    print("\nReview each pack folder (REVIEW.md says what to check), then give the go-ahead:")
    print("   ./jf review            list packs        ./jf review --open 3     open a folder        ./jf review --ok 3,7   approve the documents")
