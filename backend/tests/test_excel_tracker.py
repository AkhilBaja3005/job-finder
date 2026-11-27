"""Offline tests for the Excel tracker and closing-date extraction (no network, no LLM)."""

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import closing_date as cd  # noqa: E402
from backend.services.excel_tracker import (  # noqa: E402
    ExcelTracker, HEADERS, job_key, normalize_job_url, record_from_payload,
)

TODAY = date(2026, 11, 20)


def _job(n=1, **kw):
    base = {"company": f"Co{n}", "job_title": f"AI Intern {n}", "location": "London", "platform": "Greenhouse",
            "overall_ats": 70 + n, "job_url": f"https://boards.greenhouse.io/co{n}/jobs/{n}", "status": "New"}
    base.update(kw)
    return record_from_payload(base)


@pytest.fixture
def tracker(tmp_path):
    return ExcelTracker(str(tmp_path / "t.xlsx"))


# ─── tracker ──────────────────────────────────────────────────────────────────
def test_creates_workbook_with_headers_and_adds_rows(tracker):
    added, skipped = tracker.add_jobs([_job(1), _job(2)])
    assert (len(added), skipped) == (2, 0)
    rows = tracker.rows()
    assert [r["ID"] for r in rows] == [1, 2]
    assert rows[0]["Applied"] == "No" and rows[0]["Status"] == "New"
    assert rows[1]["ATS %"] == 72
    assert set(HEADERS) <= set(rows[0])


def test_dedupes_by_url_and_by_company_role_location(tracker):
    tracker.add_jobs([_job(1)])
    same_url = _job(9, job_url="https://boards.greenhouse.io/co1/jobs/1/?utm=x")
    same_job_other_board = _job(1, job_url="https://jobs.lever.co/co1/zzz", platform="Lever")
    added, skipped = tracker.add_jobs([same_url, same_job_other_board])
    assert (len(added), skipped) == (0, 2)
    assert len(tracker.rows()) == 1


def test_ids_stay_unique_after_a_row_is_deleted_by_hand(tracker):
    tracker.add_jobs([_job(1), _job(2)])
    from openpyxl import load_workbook
    wb = load_workbook(tracker.path)
    wb["Jobs"].delete_rows(2)  # user deletes ID 1 in Excel
    wb.save(tracker.path)
    tracker.add_jobs([_job(3)])
    assert [r["ID"] for r in tracker.rows()] == [2, 3]  # max+1, no clash with ID 2


def test_update_applied_sets_flag_and_date(tracker):
    tracker.add_jobs([_job(1)])
    assert tracker.update(url="https://boards.greenhouse.io/co1/jobs/1", status="applied")
    r = tracker.rows()[0]
    assert r["Status"] == "Applied" and r["Applied"] == "Yes" and r["Date Applied"] is not None
    assert tracker.update(row_id=99, status="Applied") is False


def test_hand_edits_survive_later_writes(tracker):
    tracker.add_jobs([_job(1)])
    from openpyxl import load_workbook
    wb = load_workbook(tracker.path)
    ws = wb["Jobs"]
    hdr = {c.value: c.column for c in ws[1]}
    ws.cell(row=2, column=hdr["Notes"], value="call recruiter")
    wb.save(tracker.path)
    tracker.add_jobs([_job(2)])
    assert tracker.rows()[0]["Notes"] == "call recruiter"


def test_pending_filters_and_ordering(tracker):
    soon = (TODAY + timedelta(days=3)).isoformat()
    past = (TODAY - timedelta(days=3)).isoformat()
    tracker.add_jobs([
        _job(1, overall_ats=60),
        _job(2, overall_ats=90, closing_date=soon),
        _job(3, overall_ats=95, closing_date=past),            # expired -> excluded
        _job(4, overall_ats=80, status="Skipped"),             # not open -> excluded
        _job(5, overall_ats=85),
    ])
    tracker.update(row_id=5, status="Applied")                 # already applied -> excluded
    ids = [r["ID"] for r in tracker.pending(today=TODAY)]
    assert ids == [2, 1]
    assert [r["ID"] for r in tracker.pending(min_ats=70, today=TODAY)] == [2]
    assert [r["ID"] for r in tracker.pending(limit=1, today=TODAY)] == [2]
    # explicit ids bypass status/ATS filters but not applied/expired
    assert [r["ID"] for r in tracker.pending(ids=[4, 5, 3], today=TODAY)] == [4]


def test_mark_expired_closes_only_unapplied_open_rows(tracker):
    past = (date.today() - timedelta(days=2)).isoformat()
    tracker.add_jobs([_job(1, closing_date=past), _job(2, closing_date=past), _job(3)])
    tracker.update(row_id=2, status="Applied")
    assert tracker.mark_expired() == 1
    st = {r["ID"]: r["Status"] for r in tracker.rows()}
    assert st == {1: "Closed", 2: "Applied", 3: "New"}


def test_legacy_status_mapping_and_csv_import(tmp_path, monkeypatch):
    (tmp_path / "applications_tracker").mkdir()
    csv_path = tmp_path / "applications_tracker" / "job_applications_tracker.csv"
    csv_path.write_text(
        "Company,Job Title,Location,Platform,Posted Time,Overall ATS,Skills Match,Experience Match,Role Fit,"
        "Matched Skills,Missing Skills,Salary,Seniority,Recruiter,Recruiter LinkedIn,PDF Path,LaTeX Path,Status,Job URL\n"
        "Acme,Engineer,London,Jobserve,2026-11-20; 05:19,71%,60%,0%,75%,,,,Mid,,,/x/a.pdf,,Tailored & Ready,https://x.com/j/1\n")
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    t = ExcelTracker(str(tmp_path / "applications_tracker" / "scanned_jobs.xlsx"))     # only the ORIGINAL workbook imports the old CSV
    added, _ = t.add_jobs([_job(1)])
    rows = t.rows()
    assert rows[0]["Company"] == "Acme" and rows[0]["Status"] == "New" and rows[0]["ATS %"] == 71
    assert rows[1]["ID"] == 2 and len(added) == 1


def test_helpers():
    assert normalize_job_url("https://X.com/job/1/?a=b") == "https://x.com/job/1"
    assert job_key("Acme Ltd.", "AI Intern", "London") == job_key("acme ltd", "AI  intern", "LONDON")
    assert record_from_payload({"overall_ats": "71%", "junk": 1}) == {"ATS %": "71%"}


# ─── closing dates ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Closing date: 30 November 2026", date(2026, 11, 30)),
    ("Applications close on 5th Dec 2026.", date(2026, 12, 5)),
    ("Application deadline - Dec 14, 2026", date(2026, 12, 14)),
    ("Please apply by 01/12/2026 at the latest", date(2026, 12, 1)),
    ("Deadline: 2026-12-20", date(2026, 12, 20)),
    ("We review on a rolling basis", None),
    ("Founded 14 March 2019. Closing date: TBC", None),     # date not tied to a cue
    ("Closing date: 3 May 2031", None),                      # implausible -> noise
])
def test_extract_from_text(text, expected):
    assert cd.extract_from_text(text, today=TODAY) == expected


def test_extract_from_jsonld():
    html = ('<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":'
            '[{"@type":"JobPosting","title":"AI Intern","validThrough":"2026-12-31T23:59:00Z"}]}</script></html>')
    assert cd.extract_from_jsonld(html, today=TODAY) == date(2026, 12, 31)
    assert cd.extract_from_jsonld("<html>no ld</html>", today=TODAY) is None
    assert cd.extract_from_jsonld('<script type="application/ld+json">{bad json</script>', today=TODAY) is None


def test_from_job_prefers_structured_field_over_text():
    job = {"closing_date": "2026-12-02", "description": "Closing date: 30 November 2026"}
    assert cd.from_job(job, today=TODAY) == date(2026, 12, 2)
    assert cd.from_job({"description": "Closing date: 30 November 2026"}, today=TODAY) == date(2026, 11, 30)


def test_upgrading_an_older_workbook_adds_dropdowns_for_the_new_columns(tmp_path):
    """An older file has no Approve column: it must be appended WITH its Yes/No dropdown, at its real position."""
    from openpyxl import load_workbook
    t = ExcelTracker(str(tmp_path / "old.xlsx"))
    t.add_jobs([_job(1)])
    wb = load_workbook(t.path)
    ws = wb["Jobs"]
    col = [c.value for c in ws[1]].index("Approve") + 1
    ws.delete_cols(col)                                      # simulate a workbook from before the Approve column existed
    from openpyxl.worksheet.datavalidation import DataValidationList
    ws.data_validations = DataValidationList()
    wb.save(t.path)

    rows = t.rows()                                          # opening it upgrades the layout
    assert rows[0]["Company"] == "Co1"
    t.update(row_id=1, approve="Yes")
    ws = load_workbook(t.path)["Jobs"]
    headers = [c.value for c in ws[1]]
    from openpyxl.utils import get_column_letter
    approve_letter = get_column_letter(headers.index("Approve") + 1)
    sqrefs = [str(dv.sqref) for dv in ws.data_validations.dataValidation]
    assert any(s.startswith(f"{approve_letter}2") for s in sqrefs), (approve_letter, sqrefs)
    status_letter = get_column_letter(headers.index("Status") + 1)
    assert any(s.startswith(f"{status_letter}2") for s in sqrefs)           # Status dropdown re-pointed at its real column
    assert t.rows()[0]["Approve"] == "Yes"


def test_a_workbook_for_another_search_does_not_import_the_old_csv(tmp_path, monkeypatch):
    (tmp_path / "applications_tracker").mkdir()
    (tmp_path / "applications_tracker" / "job_applications_tracker.csv").write_text(
        "Company,Job Title,Location,Platform,Posted Time,Overall ATS,Skills Match,Experience Match,Role Fit,Matched Skills,Missing Skills,"
        "Salary,Seniority,Recruiter,Recruiter LinkedIn,PDF Path,LaTeX Path,Status,Job URL\nOld,Role,L,P,t,1%,1%,1%,1%,,,,,,,,,New,https://x.com/1\n")
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    other = ExcelTracker(str(tmp_path / "applications_tracker" / "searches" / "cyber" / "scanned_jobs.xlsx"))
    assert other.rows() == []
    other.add_jobs([_job(1)])
    assert [r["Company"] for r in other.rows()] == ["Co1"]


def test_remove_rows_keeps_hyperlinks_on_the_right_rows(tracker):
    from openpyxl import load_workbook
    tracker.add_jobs([_job(1), _job(2), _job(3)])
    assert tracker.remove_rows([2, 99]) == 1
    rows = tracker.rows()
    assert [r["ID"] for r in rows] == [1, 3] and [r["Company"] for r in rows] == ["Co1", "Co3"]
    ws = load_workbook(tracker.path)["Jobs"]
    h = [c.value for c in ws[1]]
    col = h.index("Job URL") + 1
    assert [ws.cell(row=r, column=col).hyperlink.target for r in (2, 3)] == [rows[0]["Job URL"], rows[1]["Job URL"]]
    assert ws.max_row == 3 or all(ws.cell(row=r, column=1).value is None for r in range(4, ws.max_row + 1))


def test_list_values_are_written_as_comma_separated_text(tmp_path):
    t = ExcelTracker(str(tmp_path / "t.xlsx"))
    added, _ = t.add_jobs([{"Company": "Acme", "Job Role": "Engineer", "Job URL": "https://x.test/1",
                            "Matched Skills": ["Python", "Docker"], "Missing Skills": []}])
    assert added
    row = t.rows()[0]
    assert row["Matched Skills"] == "Python, Docker"
