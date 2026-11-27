"""
`job-finder apply`: fill (and optionally submit) applications.

    job-finder apply                  work through the APPROVED queue (approved_jobs.xlsx), preview only
    job-finder apply --submit         ... and really submit them
    job-finder apply <url> | <file>   apply to specific URL(s) you name, outside the queue

Only jobs you approved are ever picked up (see `job-finder approve`), and only once you have reviewed and signed off
their application pack (`job-finder review --ok ID`): the pack's cv.pdf is uploaded and its cover letter pasted verbatim
(--no-pack skips this gate and uses your master resume). After every application both
workbooks are updated: Applied (verified submission), Needs Review (blocked / unconfirmed / failed) or
Closed (the posting is gone). A preview run (no --submit) only adds a note and never marks a row Applied.
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from job_finder import ui

logger = logging.getLogger(__name__)


def _urls_from_target(target: str) -> List[str]:
    """A single URL, or every URL found in a .txt/.csv/.json file."""
    target = target.strip()
    if os.path.isfile(target):
        print(f"[Apply] Reading URLs from file: {target}")
        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
            urls: List[str] = []
            if target.lower().endswith(".json"):
                data = json.loads(content)
                items = data if isinstance(data, list) else (data.get("urls") or data.get("jobs") or [])
                for item in items:
                    if isinstance(item, str) and item.startswith("http"):
                        urls.append(item)
                    elif isinstance(item, dict):
                        u = item.get("url") or item.get("job_url") or item.get("link")
                        if u:
                            urls.append(u)
            else:
                urls = [u.rstrip(")") for u in re.findall(r'https?://[^\s,"]+', content)]
            return list(dict.fromkeys(urls))
        except Exception as fe:
            ui.error(f"Failed to parse '{target}': {fe}")
            sys.exit(1)
    if target.startswith(("http://", "https://")):
        return [target]
    ui.error(f"'{target}' is neither an http(s) URL nor an existing file.")
    sys.exit(1)


def _classify(res: Any, submitted_mode: bool) -> Dict[str, str]:
    """
    Turn an autofill result into a tracker outcome: {"status": ..., "note": ...}.
    status is "Applied", "Needs Review", "Closed", or "" (preview: leave the row's status alone).
    """
    if not isinstance(res, dict):
        return {"status": "Needs Review", "note": f"Unexpected result: {str(res)[:150]}"}
    status = str(res.get("status") or "").lower()
    final = str(res.get("final_result") or "")
    blocker = res.get("blocker")
    shot = res.get("review_screenshot")
    extra = f" Screenshot: {shot}" if shot else ""
    if "job unavailable" in final.lower():
        return {"status": "Closed", "note": final[:150]}
    if status == "success" and res.get("auto_submit"):
        return {"status": "Applied", "note": "Submission confirmed."}
    if blocker:
        return {"status": "Needs Review", "note": f"Blocked by {blocker}. {final[:120]}{extra}".strip()}
    if status == "preview_ready" and not res.get("auto_submit"):
        return {"status": "", "note": f"Previewed (not submitted): form filled, review in browser.{extra}"}
    reason = res.get("error") or final or "Unconfirmed submission"
    return {"status": "Needs Review", "note": f"{status or 'failed'}: {str(reason)[:150]}{extra}"}


# Statuses in the scanned file that mean "don't apply to this one", even if it is still in the approved queue.
_HANDLED = ("Applied", "Interview", "Offer", "Rejected", "Skipped", "Closed", "Withdrawn")


def _handled_in_scanned(scanned, clean_status, normalize) -> Dict[str, Dict[str, Any]]:
    """URL -> scanned row for jobs you've already dealt with (e.g. applied by hand and marked Applied in Excel)."""
    out = {}
    for r in scanned.rows():
        if r.get("Job URL") and (str(r.get("Applied") or "No") == "Yes" or clean_status(r.get("Status")) in _HANDLED):
            out[normalize(r["Job URL"])] = r
    return out


def run(args: argparse.Namespace):
    import asyncio
    from applications_tracker.scheduled_job_scanner import (
        run_browser_use_autofill, find_master_resume_with_mac_tags,
        notify_user_of_failed_applications, notify_user_of_applied_applications,
    )
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services import application_pack as ap
    try:
        from services.excel_tracker import ExcelTracker, _clean_status, approved_path, normalize_job_url
    except ImportError:
        from backend.services.excel_tracker import ExcelTracker, _clean_status, approved_path, normalize_job_url

    scanned = ExcelTracker()                               # everything found (we mirror results back here)
    tracker = ExcelTracker(approved_path(scanned.path))    # the approved queue: the only list we apply from
    prof = load_profile_data() or {}
    cand = prof.get("candidate", {})
    prefs = prof.get("search_preferences", {})
    submit = bool(args.submit) and not getattr(args, "dry_run", False)

    # ── choose what to apply to ──────────────────────────────────────────────
    jobs: List[Dict[str, Any]] = []
    handled = _handled_in_scanned(scanned, _clean_status, normalize_job_url)
    try:
        from backend.services import searches as _searches
        for u, name in _searches.handled_elsewhere(exclude_scanned=scanned.path).items():
            handled.setdefault(u, {"ID": "-", "Status": "Applied", "Applied": "Yes", "_note": f"Already applied in search '{name}'"})
    except Exception:
        pass
    if args.target:
        by_url = {}
        for wb in (scanned, tracker):                      # scanned first, so approved rows win
            by_url.update({normalize_job_url(r.get("Job URL")): r for r in wb.rows() if r.get("Job URL")})
        for u in _urls_from_target(args.target):
            row = by_url.get(normalize_job_url(u))
            h = handled.get(normalize_job_url(u))
            if (row and str(row.get("Applied")) == "Yes") or h:
                print(f"[Tracker] Skipping {u}: already handled (row #{(h or row).get('ID')}, status {(h or row).get('Status')}).")
                continue
            signed = bool(row and row.get("Pack Folder") and str(row.get("Docs OK")) == "Yes" and os.path.isdir(str(row["Pack Folder"])))
            jobs.append({"url": u, "id": row.get("ID") if row else None,
                         "company": (row or {}).get("Company") or urlparse(u).netloc,
                         "title": (row or {}).get("Job Role") or urlparse(u).path.strip("/") or u,
                         "ats": (row or {}).get("ATS %"),
                         "pack": str(row["Pack Folder"]) if signed else None, "cover": (row or {}).get("Cover Letter") if signed else None})
    else:
        closed = tracker.mark_expired() + scanned.mark_expired()
        if closed:
            print(f"[Tracker] Marked {closed} listing(s) Closed (closing date passed).")
        ids = [int(x) for x in re.split(r"[,\s]+", args.ids.strip()) if x] if args.ids else None
        statuses = ("Approved", "Needs Review") if getattr(args, "retry", False) else ("Approved",)
        rows = tracker.pending(min_ats=args.min_ats, limit=None,
                               ids=ids, company=args.company, statuses=statuses)
        vetoed = [r for r in rows if normalize_job_url(r["Job URL"]) in handled]
        for r in vetoed:                                   # the scanned file says it's done: believe it, and sync the queue
            h = handled[normalize_job_url(r["Job URL"])]
            print(f"[Queue] Skipping #{r.get('ID')} {r.get('Company')}: marked {h.get('Status')} in the scanned file.")
            tracker.update(url=r["Job URL"], status=h.get("Status") or "Applied", append_note=h.get("_note") or "Marked in the scanned file")
        rows = [r for r in rows if r not in vetoed]
        # Review gate: a job is only applied to once you have read its CV / cover letter and signed it off.
        no_pack = bool(getattr(args, "no_pack", False))
        for r in rows:
            folder = str(r.get("Pack Folder") or "")
            has_pack = bool(folder) and os.path.isdir(folder)
            if not no_pack and not has_pack:
                ui.warn(f"[Review] #{r.get('ID')} {r.get('Company')}: no application pack yet. Run `job-finder prepare --ids {r.get('ID')}` (or apply with --no-pack).")
                continue
            if not no_pack and str(r.get("Docs OK") or "No") != "Yes":
                ui.warn(f"[Review] #{r.get('ID')} {r.get('Company')}: documents not signed off. "
                        f"`job-finder review --open {r.get('ID')}`, then `job-finder review --ok {r.get('ID')}`.")
                continue
            jobs.append({"url": r["Job URL"], "id": r.get("ID"), "company": r.get("Company"),
                         "title": r.get("Job Role"), "ats": r.get("ATS %"),
                         "pack": folder if (has_pack and not no_pack) else None,
                         "cover": r.get("Cover Letter") if (has_pack and not no_pack) else None})
        jobs.sort(key=lambda j: int(float(j["ats"] or 0)), reverse=True)
        if args.limit and args.limit > 0:
            jobs = jobs[:args.limit]
        if rows and not jobs:
            return
        if not jobs:
            ui.info(f"Nothing approved to apply to in {tracker.path}.")
            ui.info("1) open the scanned file and set  Approve = Yes  on the jobs you want:  " + scanned.path)
            ui.info("2) run  `job-finder approve`  to move them into the approved queue, then run apply again.")
            waiting = [r for r in scanned.rows() if str(r.get("Approve") or "").lower() == "yes" and str(r.get("Status")) != "Approved"
                       and str(r.get("Applied")) != "Yes"]
            if waiting:
                ui.warn(f"{len(waiting)} row(s) are marked Approve = Yes in the scanned file but not approved yet: run `job-finder approve`.")
            return

    mode = "SUBMIT (applications will be sent)" if submit else "PREVIEW (forms are filled, nothing is submitted)"
    ui.print_table(f"Applying to {len(jobs)} job(s): {mode}", ["ID", "ATS", "Company", "Role"],
                   [[str(j["id"] or "-"), f"{j['ats']}%" if j["ats"] is not None else "-",
                     str(j["company"])[:28], str(j["title"])[:50]] for j in jobs])

    if submit and not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            ui.error("Refusing to submit without confirmation in a non-interactive shell. Re-run with --yes to confirm.")
            sys.exit(2)
        if input(f"Submit {len(jobs)} application(s) now? This cannot be undone. [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled; nothing was submitted.")
            return

    def _pack_cv(job):
        return os.path.join(job["pack"], "cv.pdf") if job.get("pack") and os.path.isfile(os.path.join(job["pack"], "cv.pdf")) else None
    need_master = any(not _pack_cv(j) for j in jobs)
    target_resume = args.resume or (find_master_resume_with_mac_tags() if need_master else None)
    if need_master and (not target_resume or not os.path.isfile(target_resume)):
        ui.error(f"Your resume file was not found: {target_resume or '(MASTER_RESUME_PATH is not set)'}")
        ui.info("Put your resume PDF somewhere permanent, set MASTER_RESUME_PATH=/full/path/resume.pdf in .env "
                "(or pass --resume), then run again. Nothing was opened or submitted.")
        sys.exit(1)
    applied: List[Dict[str, Any]] = []
    problems: List[Dict[str, Any]] = []
    stamp = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")  # noqa: E731

    def _record(job: Dict[str, Any], outcome: Dict[str, str]) -> None:
        note = f"[{stamp()}] {outcome['note']}"
        fields: Dict[str, Any] = {"Status": outcome["status"]} if outcome["status"] else {}
        try:
            if not tracker.update(url=job["url"], append_note=note, **fields):
                # Applied to a URL that isn't in the queue (explicit URL mode): add it so history is complete
                tracker.add_jobs([{"Company": job["company"], "Job Role": job["title"], "Job URL": job["url"],
                                   "Platform": "Manual", "Status": outcome["status"] or "New", "Approve": "Yes", "Notes": note}])
            scanned.update(url=job["url"], append_note=note, **fields)   # mirror into the scanned file if the job is there
        except Exception as e:  # tracker problems must never lose the application result
            print(f"[Tracker] Could not record result for {job['url']}: {e}")

    async def _batch() -> None:
        for idx, job in enumerate(jobs, 1):
            print(f"\n{'=' * 60}\n[{idx}/{len(jobs)}] {job['title']} @ {job['company']}\n{job['url']}\n{'=' * 60}")
            cv_file = _pack_cv(job) or target_resume
            letter = ap.read_cover_letter(job.get("pack")) if job.get("cover") == "Yes" else {"text": None, "pdf": None}
            print(f"   CV: {os.path.relpath(cv_file) if cv_file else '-'}   cover letter: {'reviewed text from the pack' if letter['text'] else 'none from the pack'}")
            try:
                res = await asyncio.wait_for(
                    run_browser_use_autofill(
                        job["url"], resume_data=cand, resume_pdf_path=cv_file,
                        auto_submit=submit, model_name=args.model, headless=args.headless, max_steps=args.max_steps,
                        cover_letter_text=letter["text"], cover_letter_path=letter["pdf"],
                    ),
                    timeout=args.timeout,
                )
            except asyncio.TimeoutError:
                res = {"status": "failed", "error": f"timed out after {int(args.timeout)}s"}
            except Exception as ex:
                res = {"status": "failed", "error": str(ex)}
            outcome = _classify(res, submit)
            _record(job, outcome)
            if job.get("pack"):
                shot = ap.copy_into_pack(job["pack"], res.get("review_screenshot") if isinstance(res, dict) else None,
                                         f"screenshot_{datetime.now().strftime('%Y%m%d-%H%M%S')}.png")
                ap.append_apply_log(job["pack"], f"{'SUBMIT' if submit else 'PREVIEW'} -> {outcome['status'] or 'Previewed'}: {outcome['note']}"
                                    f" (CV: {os.path.basename(cv_file or '-')}, cover letter: {'pasted from pack' if letter['text'] else 'none'})"
                                    + (f" [screenshot: {os.path.basename(shot)}]" if shot else ""))
            label = outcome["status"] or "Previewed"
            print(f"[{idx}/{len(jobs)}] -> {label}: {outcome['note']}")
            item = {"url": job["url"], "title": job["title"], "company": job["company"], "reason": outcome["note"]}
            if outcome["status"] == "Applied":
                applied.append(item)
            elif outcome["status"] in ("Needs Review", "Closed"):
                problems.append(item)

    asyncio.run(_batch())

    # Summary email (only when something was actually submitted or needs attention)
    to = cand.get("email") or os.getenv("NOTIFY_EMAIL", "")
    try:
        if applied:
            notify_user_of_applied_applications(applied, to_email=to)
        if problems:
            notify_user_of_failed_applications(problems, to_email=to)
    except Exception as mail_err:
        print(f"[Email Alert] Note: could not send summary email: {mail_err}")

    ui.key_values("Apply summary", {
        "Processed": len(jobs), "Applied": len(applied), "Needs review / closed": len(problems),
        "Previewed only": len(jobs) - len(applied) - len(problems), "Tracker": tracker.path,
    })
    if problems:
        ui.print_table("Needs attention", ["Company", "Role", "Why"],
                       [[str(p["company"])[:24], str(p["title"])[:36], str(p["reason"])[:80]] for p in problems])
