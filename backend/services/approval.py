"""
approval.py - the scanned -> approved hand-off.

    scanned_jobs.xlsx   everything `scan` found; you review it and set Approve = Yes on the rows you want
    approved_jobs.xlsx  the queue `apply` works from (nothing gets in without being approved)

`approve_jobs` copies chosen rows from scanned to approved (keeping their IDs) and marks them Approved in
the scanned file. Rows can be chosen three ways, combined freely:
  - by hand in Excel: Approve = Yes (or Status = Approved) on the row, then run `job-finder approve`
  - explicitly: ids=[3, 7]
  - in bulk: min_ats=85 (every open row scoring at least that)
Rows that can't be applied to are never copied, and the reason is reported: already applied, knocked out
(Skipped), closed / past its closing date, or missing a URL.
"""

from datetime import date
from typing import Any, Dict, Iterable, List, Optional

try:
    from .excel_tracker import ExcelTracker, _clean_status, _to_date, _to_int, normalize_job_url
except ImportError:  # pragma: no cover
    from excel_tracker import ExcelTracker, _clean_status, _to_date, _to_int, normalize_job_url

# Status values that mean "this row can still be approved".
APPROVABLE = ("New", "Shortlisted", "Approved")
_BLOCK_REASON = {
    "Applied": "already applied", "Interview": "already applied", "Offer": "already applied",
    "Rejected": "rejected", "Skipped": "skipped (you fail a hard requirement or marked it Skipped)",
    "Closed": "closed", "Withdrawn": "withdrawn", "Needs Review": "needs review (set Status back to New to re-approve)",
}


def approve_jobs(scanned: ExcelTracker, approved: ExcelTracker, ids: Optional[Iterable[int]] = None,
                 min_ats: Optional[int] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Copy chosen scanned rows into the approved workbook. Returns {approved, already, skipped}."""
    today = today or date.today()
    wanted = {int(i) for i in ids} if ids else set()
    queue = {normalize_job_url(r.get("Job URL")): r for r in approved.rows() if r.get("Job URL")}
    chosen: List[Dict[str, Any]] = []
    revive: List[Dict[str, Any]] = []     # in the queue as Withdrawn: bring back instead of duplicating
    already: List[int] = []
    skipped: List[Dict[str, Any]] = []

    for r in scanned.rows():
        rid = _to_int(r.get("ID"))
        status = _clean_status(r.get("Status"))
        marked = str(r.get("Approve") or "").strip().lower() == "yes" or status == "Approved"
        by_ats = min_ats is not None and (_to_int(r.get("ATS %")) or 0) >= min_ats and status in APPROVABLE
        if not (marked or rid in wanted or by_ats):
            continue
        url = r.get("Job URL")
        reason = None
        if str(r.get("Applied") or "No") == "Yes" or status in ("Applied", "Interview", "Offer"):
            reason = "already applied"
        elif status in _BLOCK_REASON and status != "Approved":
            reason = _BLOCK_REASON[status]
        elif not url:
            reason = "no job URL"
        else:
            d = _to_date(r.get("Closing Date"))
            if d and d < today:
                reason = f"closing date passed ({d.isoformat()})"
        if reason:
            if not by_ats or marked or rid in wanted:   # don't list every low-score row a bulk rule passed over
                skipped.append({"id": rid, "company": r.get("Company"), "role": r.get("Job Role"), "reason": reason})
            continue
        in_queue = queue.get(normalize_job_url(url))
        if in_queue is not None:
            if _clean_status(in_queue.get("Status")) == "Withdrawn":
                revive.append(r)
            else:
                already.append(rid)
            continue
        chosen.append(r)

    records = []
    for r in chosen:
        rec = {k: v for k, v in r.items() if not k.startswith("_") and v not in (None, "")}
        rec.update({"Status": "Approved", "Approve": "Yes", "Applied": "No"})
        records.append(rec)
    added, _dups = approved.add_jobs(records) if records else ([], 0)
    if revive:
        approved.update_many([({"url": r.get("Job URL")}, {"Status": "Approved", "Approve": "Yes"}, None) for r in revive])
        added = added + [dict(r, Status="Approved") for r in revive]

    # Reflect it in the scanned file in one save: Approved + Approve=Yes.
    updates = [({"row_id": _to_int(r.get("ID"))}, {"Status": "Approved", "Approve": "Yes"}, None)
               for r in chosen + revive]
    updates += [({"row_id": rid}, {"Status": "Approved", "Approve": "Yes"}, None) for rid in already]
    if updates:
        scanned.update_many(updates)
    return {"approved": added, "already": already, "skipped": skipped}


def withdraw_jobs(scanned: ExcelTracker, approved: ExcelTracker, ids: Iterable[int]) -> Dict[str, List[int]]:
    """Take rows back out of the queue (only if not yet applied): approved row -> Withdrawn, scanned row -> New."""
    ids = {int(i) for i in ids}
    done, refused = [], []
    updates_a, updates_s = [], []
    for r in approved.rows():
        rid = _to_int(r.get("ID"))
        if rid not in ids:
            continue
        if str(r.get("Applied") or "No") == "Yes":
            refused.append(rid)
            continue
        updates_a.append(({"row_id": rid}, {"Status": "Withdrawn", "Approve": "No"}, None))
        updates_s.append(({"row_id": rid}, {"Status": "New", "Approve": "No"}, None))
        done.append(rid)
    if updates_a:
        approved.update_many(updates_a)
        scanned.update_many(updates_s)
    return {"withdrawn": done, "refused": refused}
