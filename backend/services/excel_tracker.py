"""
excel_tracker.py - the Excel job tracker (the single source of truth for scan + apply).

One row per job. `scan` adds rows; `apply` picks rows and updates them. You can also edit the
sheet by hand (change a Status, set Applied, add Notes) and the next run respects it.

    ID | Company | Job Role | Location | Platform | Posted | Closing Date | Applied | Status | ATS % | ...

Design notes
- Every call loads the workbook, changes it and saves atomically, so edits you make in Excel between
  runs are never overwritten by a stale in-memory copy. Close or save the file in Excel before a run.
- Rows are de-duplicated by normalized URL, and by company + role + location (same job, different board).
- If the .xlsx does not exist yet, the legacy CSV tracker (if any) is imported once.
"""

import csv
import os
import re
import tempfile
import threading
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

SHEET = "Jobs"
MAX_ROWS = 5000  # range covered by dropdowns / conditional formatting

# (header, width). Order = column order in the sheet.
COLUMNS: List[Tuple[str, int]] = [
    ("ID", 6), ("Company", 24), ("Job Role", 42), ("Location", 20), ("Platform", 14),
    ("Posted", 17), ("Closing Date", 14), ("Applied", 9), ("Status", 15), ("Approve", 9), ("ATS %", 8),
    ("Skills %", 9), ("Experience %", 12), ("Role Fit %", 10), ("Scored By", 11), ("Matched Skills", 32),
    ("Missing Skills", 32), ("Fit Summary", 55), ("UK Sponsor", 11), ("Level", 11), ("Role Level", 11), ("Years Exp", 10), ("Match", 9), ("Salary", 18),
    ("Date Found", 12), ("Date Applied", 12), ("Notes", 40), ("Docs OK", 9), ("Cover Letter", 12),
    ("Pack Folder", 42), ("Job URL", 55),
]
HEADERS = [h for h, _ in COLUMNS]

STATUSES = ["New", "Shortlisted", "Approved", "Applied", "Needs Review", "Interview", "Offer", "Rejected",
            "Closed", "Skipped", "Withdrawn"]
OPEN_STATUSES = ("New", "Shortlisted", "Approved")  # not applied yet and still worth acting on
DATE_FMT = "dd mmm yyyy"

_lock = threading.RLock()


class TrackerLockedError(RuntimeError):
    """The .xlsx could not be written (usually open and locked in Excel)."""


# ─── helpers ──────────────────────────────────────────────────────────────────
def normalize_job_url(u: Optional[str]) -> str:
    """
    Normalize a job URL for de-duplication. Preserves per-job keys for query-based boards
    (Indeed ``jk=``, LinkedIn ``currentJobId=``) so they don't all collapse to one URL.
    """
    if not u or not str(u).strip():
        return ""
    raw = str(u).strip().rstrip("/").lower()
    if "jk=" in raw:
        m = re.search(r"jk=([a-f0-9]{16})", raw)
        if m:
            domain = "uk.indeed.com" if "uk.indeed.com" in raw else "indeed.com"
            return f"{domain}/viewjob?jk={m.group(1)}"
    if "currentjobid=" in raw:
        m = re.search(r"currentjobid=(\d+)", raw)
        if m:
            return f"linkedin.com/jobs/view/{m.group(1)}"
    return raw.split("?")[0].rstrip("/").lower()


def _norm_text(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def job_key(company: Any, role: Any, location: Any) -> str:
    """Identity of a job across boards: same company + role + location."""
    return "|".join(_norm_text(x) for x in (company, role, location))


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    digits = re.sub(r"[^0-9.]", "", str(v))
    try:
        return int(round(float(digits))) if digits else None
    except ValueError:
        return None


def _to_date(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        from services.closing_date import parse_date
    except ImportError:
        from backend.services.closing_date import parse_date
    return parse_date(v)


def default_path() -> str:
    """The SCANNED workbook (env JOB_FINDER_TRACKER_XLSX overrides)."""
    env = os.getenv("JOB_FINDER_TRACKER_XLSX")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    try:
        from config.constants import get_tracker_xlsx_path
    except ImportError:
        from backend.config.constants import get_tracker_xlsx_path
    return get_tracker_xlsx_path()


def approved_path(scanned: Optional[str] = None) -> str:
    """
    The APPROVED workbook that sits next to the scanned one (env JOB_FINDER_APPROVED_XLSX overrides):
    scanned_jobs.xlsx -> approved_jobs.xlsx, anything_else.xlsx -> anything_else_approved.xlsx.
    """
    env = os.getenv("JOB_FINDER_APPROVED_XLSX")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    scanned = scanned or default_path()
    folder, name = os.path.split(scanned)
    if name == "scanned_jobs.xlsx":
        return os.path.join(folder, "approved_jobs.xlsx")
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, f"{stem}_approved{ext}")


def _legacy_csv_path() -> Optional[str]:
    try:
        try:
            from config.constants import get_tracker_csv_path
        except ImportError:
            from backend.config.constants import get_tracker_csv_path
        p = get_tracker_csv_path()
        return p if os.path.exists(p) else None
    except Exception:
        return None


# Mapping from the snake_case payload used across the codebase to sheet columns.
_PAYLOAD_MAP = {
    "company": "Company", "job_title": "Job Role", "title": "Job Role", "location": "Location",
    "platform": "Platform", "posted_time": "Posted", "closing_date": "Closing Date",
    "status": "Status", "overall_ats": "ATS %", "score": "ATS %", "skills_match": "Skills %",
    "experience_match": "Experience %", "role_fit": "Role Fit %", "matched_skills": "Matched Skills",
    "missing_skills": "Missing Skills", "fit_summary": "Fit Summary", "scored_by": "Scored By",
    "uk_sponsor": "UK Sponsor", "seniority": "Level",
    "level": "Level", "salary": "Salary", "notes": "Notes", "job_url": "Job URL", "url": "Job URL",
    "applied": "Applied", "approve": "Approve", "docs_ok": "Docs OK", "cover_letter": "Cover Letter",
    "pack_folder": "Pack Folder", "role_level": "Role Level", "years_exp": "Years Exp", "match": "Match",
}


def record_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a scanner/tracker payload into {column header: value}. Unknown keys are ignored."""
    rec: Dict[str, Any] = {}
    for key, col in _PAYLOAD_MAP.items():
        if key in payload and payload[key] not in (None, ""):
            rec.setdefault(col, payload[key])
    return rec


def _clean_status(status: Any) -> str:
    """Map free-form/legacy statuses onto the dropdown vocabulary."""
    s = str(status or "").strip()
    if not s:
        return "New"
    for known in STATUSES:
        if s.lower() == known.lower():
            return known
    low = s.lower()
    if low in ("applied", "autofilled", "submitted", "success"):
        return "Applied"
    if low.startswith("needs review") or low in ("failed", "blocked"):
        return "Needs Review"
    if low in ("closed", "expired"):
        return "Closed"
    if low in ("skip", "ignored", "rejected by me"):
        return "Skipped"
    return "New"  # Ready to Apply / Tailored & Ready / Saved & Scored / tailored / saved ...


# ─── the tracker ──────────────────────────────────────────────────────────────
class ExcelTracker:
    def __init__(self, path: Optional[str] = None):
        self.path = os.path.abspath(path) if path else default_path()
        if path is None and not os.getenv("JOB_FINDER_TRACKER_XLSX"):
            self._migrate_legacy_xlsx()

    def _is_original_workbook(self) -> bool:
        """Only the original scanned_jobs.xlsx may import the old CSV tracker; per-search workbooks start empty."""
        try:
            try:
                from config.constants import get_tracker_xlsx_path
            except ImportError:
                from backend.config.constants import get_tracker_xlsx_path
            return os.path.abspath(self.path) == os.path.abspath(get_tracker_xlsx_path())
        except Exception:
            return False

    def _migrate_legacy_xlsx(self) -> None:
        """job_applications_tracker.xlsx (earlier name) -> scanned_jobs.xlsx, once."""
        try:
            try:
                from config.constants import get_legacy_tracker_xlsx_path
            except ImportError:
                from backend.config.constants import get_legacy_tracker_xlsx_path
            old = get_legacy_tracker_xlsx_path()
            if os.path.basename(self.path) == "scanned_jobs.xlsx" and not os.path.exists(self.path) and os.path.exists(old):
                os.replace(old, self.path)
        except Exception:
            pass

    # -- workbook plumbing ----------------------------------------------------
    def _new_workbook(self) -> Workbook:
        wb = Workbook()
        ws = wb.active
        ws.title = SHEET
        ws.append(HEADERS)
        head_fill = PatternFill("solid", start_color="1F3864")
        for i, (name, width) in enumerate(COLUMNS, start=1):
            c = ws.cell(row=1, column=i)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(i)].width = width
        ws.freeze_panes = "D2"  # keep ID/Company/Role visible
        ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{MAX_ROWS}"
        self._add_validation_and_formats(ws)
        return wb

    def _col(self, name: str, ws=None) -> str:
        """Column letter for `name`: from the sheet's own header row when given (older files differ), else the default layout."""
        if ws is not None:
            hdr = self._headers(ws)
            if name in hdr:
                return get_column_letter(hdr[name])
        return get_column_letter(HEADERS.index(name) + 1)

    def _add_validation_and_formats(self, ws) -> None:
        col = lambda n: self._col(n, ws)  # noqa: E731
        status_dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
        applied_dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
        approve_dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
        docs_dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
        for dv in (status_dv, applied_dv, approve_dv, docs_dv):
            ws.add_data_validation(dv)
        docs_dv.add(f"{col('Docs OK')}2:{col('Docs OK')}{MAX_ROWS}")
        status_dv.add(f"{col('Status')}2:{col('Status')}{MAX_ROWS}")
        applied_dv.add(f"{col('Applied')}2:{col('Applied')}{MAX_ROWS}")
        approve_dv.add(f"{col('Approve')}2:{col('Approve')}{MAX_ROWS}")

        last = get_column_letter(max(ws.max_column, len(COLUMNS)))
        rng = f"A2:{last}{MAX_ROWS}"
        a, c = col("Applied"), col("Closing Date")
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'${a}2="Yes"'], fill=PatternFill("solid", start_color="E2EFDA", end_color="E2EFDA"), stopIfTrue=True))
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f"AND(ISNUMBER(${c}2),${c}2<TODAY())"], font=Font(color="999999"), stopIfTrue=True))
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'${col("Status")}2="Approved"'], fill=PatternFill("solid", start_color="DDEBF7", end_color="DDEBF7"), stopIfTrue=True))
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f"AND(ISNUMBER(${c}2),${c}2>=TODAY(),${c}2-TODAY()<=7)"],
            fill=PatternFill("solid", start_color="FCE4D6", end_color="FCE4D6")))

    def _open(self) -> Workbook:
        if os.path.exists(self.path):
            wb = load_workbook(self.path)
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            if self._ensure_columns(ws):
                self._refresh_validation_and_formats(ws)
            return wb
        wb = self._new_workbook()
        self._import_legacy_csv(wb[SHEET])
        return wb

    def _ensure_columns(self, ws) -> bool:
        """Append any expected columns an older/hand-edited sheet is missing. Returns True if any were added."""
        present = {str(c.value).strip() for c in ws[1] if c.value}
        added = False
        for name, width in COLUMNS:
            if name not in present:
                col = ws.max_column + 1
                head = ws.cell(row=1, column=col, value=name)
                head.font = Font(bold=True, color="FFFFFF")
                head.fill = PatternFill("solid", start_color="1F3864")
                ws.column_dimensions[get_column_letter(col)].width = width
                added = True
        return added

    def _refresh_validation_and_formats(self, ws) -> None:
        """Rebuild dropdowns and row colouring so they cover columns added to an older workbook."""
        from openpyxl.formatting.formatting import ConditionalFormattingList
        from openpyxl.worksheet.datavalidation import DataValidationList
        ws.data_validations = DataValidationList()
        ws.conditional_formatting = ConditionalFormattingList()
        self._add_validation_and_formats(ws)
        ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{MAX_ROWS}"

    def _headers(self, ws) -> Dict[str, int]:
        return {str(c.value).strip(): c.column for c in ws[1] if c.value}

    def _save(self, wb: Workbook) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(self.path))
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, self.path)
        except PermissionError as e:
            raise TrackerLockedError(f"Cannot write {self.path}: close it in Excel and retry ({e})") from e
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # -- row access -----------------------------------------------------------
    def _rows(self, ws) -> List[Dict[str, Any]]:
        hdr = self._headers(ws)
        out = []
        for r in range(2, ws.max_row + 1):
            row = {name: ws.cell(row=r, column=col).value for name, col in hdr.items()}
            if not (row.get("Company") or row.get("Job Role")):
                continue  # a job needs a company or a role; skips blank/orphan formatted rows
            row["_row"] = r
            out.append(row)
        return out

    def _write_row(self, ws, r: int, values: Dict[str, Any]) -> None:
        hdr = self._headers(ws)
        for name, val in values.items():
            col = hdr.get(name)
            if col is None:
                continue
            if isinstance(val, (list, tuple, set)):                      # e.g. matched skills: one cell, comma-separated
                val = ", ".join(str(x) for x in val if x not in (None, ""))
            elif isinstance(val, dict):
                val = "; ".join(f"{k}: {v}" for k, v in val.items())
            cell = ws.cell(row=r, column=col)
            if name == "Closing Date" or name in ("Date Found", "Date Applied"):
                d = _to_date(val)
                cell.value = d
                if d:
                    cell.number_format = DATE_FMT
            elif name.endswith("%"):
                n = _to_int(val)
                cell.value = n
                if n is not None:
                    cell.number_format = '0"%"'
            elif name == "Job URL":
                cell.value = val or None
                if val and str(val).startswith("http"):
                    cell.hyperlink = str(val)
                    cell.font = Font(color="0563C1", underline="single")
            else:
                cell.value = val
                if name in ("Matched Skills", "Missing Skills", "Fit Summary", "Notes"):
                    cell.alignment = Alignment(wrap_text=False, vertical="top")

    def _import_legacy_csv(self, ws) -> None:
        csv_path = _legacy_csv_path() if self._is_original_workbook() else None
        if not csv_path:
            return
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                legacy = list(csv.DictReader(f))
        except Exception:
            return
        for i, row in enumerate(legacy, start=1):
            pdf = (row.get("PDF Path") or "").strip()
            rec = {
                "ID": i, "Company": row.get("Company"), "Job Role": row.get("Job Title"),
                "Location": row.get("Location"), "Platform": row.get("Platform"), "Posted": row.get("Posted Time"),
                "Applied": "Yes" if _clean_status(row.get("Status")) == "Applied" else "No",
                "Status": _clean_status(row.get("Status")), "ATS %": row.get("Overall ATS"),
                "Skills %": row.get("Skills Match"), "Experience %": row.get("Experience Match"),
                "Role Fit %": row.get("Role Fit"), "Matched Skills": row.get("Matched Skills"),
                "Missing Skills": row.get("Missing Skills"), "Level": row.get("Seniority"),
                "Salary": row.get("Salary"), "Job URL": row.get("Job URL"),
                "Date Found": date.today(), "Notes": f"Imported from CSV. Resume: {pdf}" if pdf else "Imported from CSV.",
            }
            self._write_row(ws, self._next_row(ws), rec)

    def _next_row(self, ws) -> int:
        """First row after the last real job row (ws.max_row also counts blank-but-formatted rows)."""
        rows = self._rows(ws)
        return (max(r["_row"] for r in rows) + 1) if rows else 2

    @staticmethod
    def _next_id(rows: Sequence[Dict[str, Any]]) -> int:
        ids = [_to_int(r.get("ID")) or 0 for r in rows]
        return (max(ids) if ids else 0) + 1

    # -- public API -----------------------------------------------------------
    def rows(self) -> List[Dict[str, Any]]:
        """All rows as dicts keyed by column header (plus ``_row``). Empty list if no file yet."""
        with _lock:
            if not os.path.exists(self.path) and not (_legacy_csv_path() and self._is_original_workbook()):
                return []
            wb = self._open()
            return self._rows(wb[SHEET] if SHEET in wb.sheetnames else wb.active)

    def known_urls(self) -> set:
        return {normalize_job_url(r.get("Job URL")) for r in self.rows() if r.get("Job URL")} - {""}

    def add_jobs(self, records: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Add jobs (``{column header: value}``, see :func:`record_from_payload`). Returns
        ``(added_rows, skipped_duplicates)``. Existing rows are never modified.
        """
        records = list(records)
        with _lock:
            wb = self._open()
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            existing = self._rows(ws)
            urls = {normalize_job_url(r.get("Job URL")) for r in existing if r.get("Job URL")}
            keys = {job_key(r.get("Company"), r.get("Job Role"), r.get("Location")) for r in existing}
            next_id = self._next_id(existing)
            used_ids = {_to_int(r.get("ID")) for r in existing}
            added: List[Dict[str, Any]] = []
            skipped = 0
            for rec in records:
                u = normalize_job_url(rec.get("Job URL"))
                k = job_key(rec.get("Company"), rec.get("Job Role"), rec.get("Location"))
                if (u and u in urls) or (k.strip("|") and k in keys):
                    skipped += 1
                    continue
                status = _clean_status(rec.get("Status"))
                wanted_id = _to_int(rec.get("ID"))                 # keep the caller's ID if free (approve copies rows)
                row_id = wanted_id if wanted_id and wanted_id not in used_ids else next_id
                row = dict(rec)
                row.update({
                    "ID": row_id, "Status": status,
                    "Applied": "Yes" if status == "Applied" else "No",
                    "Date Found": rec.get("Date Found") or date.today(),
                })
                self._write_row(ws, self._next_row(ws), row)
                added.append(row)
                used_ids.add(row_id)
                next_id = max(next_id, row_id + 1)
                if u:
                    urls.add(u)
                keys.add(k)
            if added or not os.path.exists(self.path):
                self._save(wb)
            return added, skipped

    def update(self, *, url: Optional[str] = None, row_id: Optional[int] = None,
               append_note: Optional[str] = None, **fields: Any) -> bool:
        """
        Update one row, found by ``row_id`` or job ``url``. ``fields`` use column headers or payload keys.
        Setting Status to "Applied" also sets Applied=Yes and Date Applied (if empty).
        ``append_note`` adds to the row's Notes instead of replacing them.
        """
        found = self.update_many([({"url": url, "row_id": row_id}, fields, append_note)])
        return found == 1

    def update_many(self, updates: Iterable[Tuple[Dict[str, Any], Dict[str, Any], Optional[str]]]) -> int:
        """
        Apply several updates with a single load/save: ``[({"url": ..} or {"row_id": ..}, fields, append_note), ...]``.
        Returns how many rows were found and updated.
        """
        updates = list(updates)
        with _lock:
            wb = self._open()
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            rows = self._rows(ws)
            changed = 0
            for key, fields, append_note in updates:
                url, row_id = key.get("url"), key.get("row_id")
                want_url = normalize_job_url(url) if url else ""
                target = None
                for r in rows:
                    if row_id is not None and _to_int(r.get("ID")) == int(row_id):
                        target = r
                        break
                    if want_url and normalize_job_url(r.get("Job URL")) == want_url:
                        target = r
                        break
                if target is None:
                    continue
                values = {(_PAYLOAD_MAP.get(k, k)): v for k, v in fields.items()}
                if "Status" in values:
                    values["Status"] = _clean_status(values["Status"])
                    if values["Status"] == "Applied":
                        values["Applied"] = "Yes"
                        if not target.get("Date Applied"):
                            values["Date Applied"] = date.today()
                if append_note:
                    prior = str(target.get("Notes") or "").strip()
                    values["Notes"] = f"{prior} | {append_note}" if prior else append_note
                self._write_row(ws, target["_row"], values)
                target.update(values)          # keep the in-memory copy current for later updates in this batch
                changed += 1
            if changed:
                self._save(wb)
            return changed

    def remove_rows(self, row_ids: Iterable[int]) -> int:
        """
        Delete rows by ID. The sheet is rewritten (not row-deleted) so hyperlinks stay attached to the right rows.
        Returns how many rows were removed.
        """
        gone = {int(i) for i in row_ids}
        with _lock:
            if not os.path.exists(self.path):
                return 0
            wb = self._open()
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            rows = self._rows(ws)
            keep = [r for r in rows if _to_int(r.get("ID")) not in gone]
            removed = len(rows) - len(keep)
            if not removed:
                return 0
            hdr = self._headers(ws)
            ws.delete_rows(2, max(ws.max_row, 2))
            ws._hyperlinks = []
            for n, r in enumerate(keep, start=2):
                self._write_row(ws, n, {k: v for k, v in r.items() if k in hdr})
            self._save(wb)
            return removed

    def mark_expired(self, today: Optional[date] = None) -> int:
        """Set Status=Closed on unapplied open rows whose closing date has passed. Returns the count."""
        today = today or date.today()
        with _lock:
            if not os.path.exists(self.path):
                return 0
            wb = self._open()
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            n = 0
            for r in self._rows(ws):
                d = _to_date(r.get("Closing Date"))
                if (d and d < today and str(r.get("Applied") or "No") != "Yes"
                        and _clean_status(r.get("Status")) in OPEN_STATUSES):
                    self._write_row(ws, r["_row"], {"Status": "Closed"})
                    n += 1
            if n:
                self._save(wb)
            return n

    def pending(self, *, min_ats: Optional[int] = None, limit: Optional[int] = None,
                ids: Optional[Sequence[int]] = None, company: Optional[str] = None,
                statuses: Sequence[str] = OPEN_STATUSES, today: Optional[date] = None) -> List[Dict[str, Any]]:
        """
        Rows `apply` should work on: not applied, status open, not past closing date, URL present.
        Explicit ``ids`` bypass the status / ATS filters (but never re-apply to an applied row).
        Best ATS first; ties broken by soonest closing date.
        """
        today = today or date.today()
        wanted = {int(i) for i in ids} if ids else None
        out = []
        for r in self.rows():
            if str(r.get("Applied") or "No") == "Yes" or not r.get("Job URL"):
                continue
            rid = _to_int(r.get("ID"))
            if wanted is not None:
                if rid not in wanted:
                    continue
            else:
                if _clean_status(r.get("Status")) not in statuses:
                    continue
                ats = _to_int(r.get("ATS %"))
                if min_ats is not None and (ats is None or ats < min_ats):
                    continue
            d = _to_date(r.get("Closing Date"))
            if d and d < today:
                continue
            if company and company.lower() not in str(r.get("Company") or "").lower():
                continue
            out.append(r)
        far = date.max
        out.sort(key=lambda r: (-(_to_int(r.get("ATS %")) or 0), _to_date(r.get("Closing Date")) or far))
        return out[:limit] if limit and limit > 0 else out

    def summary(self) -> Dict[str, Any]:
        rows = self.rows()
        by_status: Dict[str, int] = {}
        for r in rows:
            s = _clean_status(r.get("Status"))
            by_status[s] = by_status.get(s, 0) + 1
        return {"total": len(rows), "applied": sum(1 for r in rows if str(r.get("Applied")) == "Yes"), "by_status": by_status}

    def legacy_entries(self) -> List[Dict[str, Any]]:
        """Rows in the dict shape the older JSON/CSV tracker code (``list_applications``) expects."""
        out = []
        for r in self.rows():
            found = _to_date(r.get("Date Found"))
            ts = datetime.combine(found, datetime.min.time()).timestamp() if found else 0
            out.append({
                "company": r.get("Company") or "", "job_title": r.get("Job Role") or "",
                "job_url": r.get("Job URL") or "", "status": r.get("Status") or "New",
                "score": _to_int(r.get("ATS %")), "closing_date": str(_to_date(r.get("Closing Date")) or ""),
                "applied": str(r.get("Applied") or "No"), "source_mode": str(r.get("Platform") or "").lower(),
                "created_at": str(found or ""), "updated_at": str(_to_date(r.get("Date Applied")) or found or ""),
                "timestamp": ts,
            })
        return out


def get_tracker(path: Optional[str] = None) -> ExcelTracker:
    return ExcelTracker(path)
