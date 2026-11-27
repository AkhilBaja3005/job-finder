"""Offline tests for the scanned -> approved hand-off (two Excel workbooks)."""

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.approval import approve_jobs, withdraw_jobs  # noqa: E402
from backend.services.excel_tracker import ExcelTracker, approved_path  # noqa: E402

FUTURE = (date.today() + timedelta(days=10)).isoformat()
PAST = (date.today() - timedelta(days=2)).isoformat()


@pytest.fixture
def books(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_FINDER_APPROVED_XLSX", raising=False)
    scanned = ExcelTracker(str(tmp_path / "scanned_jobs.xlsx"))
    approved = ExcelTracker(approved_path(scanned.path))
    mk = lambda n, ats, **kw: {"Company": f"Co{n}", "Job Role": f"AI Intern {n}", "Location": "London",   # noqa: E731
                               "ATS %": ats, "Job URL": f"https://co{n}.io/j/{n}", "Status": "New",
                               "Fit Summary": f"fit {n}", "Scored By": "AI", **kw}
    scanned.add_jobs([mk(1, 90), mk(2, 80), mk(3, 70), mk(4, 60, Status="Skipped"), mk(5, 95, **{"Closing Date": PAST}),
                      mk(6, 85, **{"Closing Date": FUTURE})])
    return scanned, approved


def statuses(t):
    return {r["ID"]: r["Status"] for r in t.rows()}


def test_approved_path_naming(tmp_path):
    assert approved_path(str(tmp_path / "scanned_jobs.xlsx")) == str(tmp_path / "approved_jobs.xlsx")
    assert approved_path(str(tmp_path / "mine.xlsx")) == str(tmp_path / "mine_approved.xlsx")


def test_nothing_is_approved_unless_you_mark_it(books):
    scanned, approved = books
    res = approve_jobs(scanned, approved)
    assert res == {"approved": [], "already": [], "skipped": []}
    assert approved.rows() == []


def test_marking_approve_yes_in_excel_moves_only_those_rows(books):
    scanned, approved = books
    scanned.update(row_id=1, approve="Yes")
    scanned.update(row_id=6, approve="Yes")
    res = approve_jobs(scanned, approved)
    assert [r["ID"] for r in res["approved"]] == [1, 6]
    rows = {r["ID"]: r for r in approved.rows()}
    assert set(rows) == {1, 6}                                           # IDs preserved
    assert rows[1]["Status"] == "Approved" and rows[1]["Approve"] == "Yes" and rows[1]["Applied"] == "No"
    assert rows[1]["Fit Summary"] == "fit 1" and rows[1]["ATS %"] == 90 and rows[1]["Scored By"] == "AI"
    assert rows[6]["Closing Date"].date().isoformat() == FUTURE
    assert statuses(scanned)[1] == "Approved" and statuses(scanned)[2] == "New"


def test_approving_twice_does_not_duplicate(books):
    scanned, approved = books
    scanned.update(row_id=1, approve="Yes")
    approve_jobs(scanned, approved)
    res = approve_jobs(scanned, approved)
    assert res["approved"] == [] and res["already"] == [1] and len(approved.rows()) == 1


def test_by_ids_and_by_min_ats(books):
    scanned, approved = books
    assert [r["ID"] for r in approve_jobs(scanned, approved, ids=[3])["approved"]] == [3]
    res = approve_jobs(scanned, approved, min_ats=85)
    assert sorted(r["ID"] for r in res["approved"]) == [1, 6]            # 5 (95) is expired; 4 is Skipped
    assert not res["skipped"]                                            # bulk rule doesn't list every row it passed over


def test_rows_that_cannot_be_applied_to_are_refused_with_a_reason(books):
    scanned, approved = books
    scanned.update(row_id=2, status="Applied")
    for rid in (2, 4, 5):
        scanned.update(row_id=rid, approve="Yes")
    res = approve_jobs(scanned, approved)
    reasons = {s["id"]: s["reason"] for s in res["skipped"]}
    assert "already applied" in reasons[2] and "skipped" in reasons[4] and "closing date passed" in reasons[5]
    assert res["approved"] == [] and approved.rows() == []


def test_typing_status_approved_by_hand_also_counts(books):
    scanned, approved = books
    scanned.update(row_id=3, status="Approved")
    assert [r["ID"] for r in approve_jobs(scanned, approved)["approved"]] == [3]


def test_withdraw_and_reapprove(books):
    scanned, approved = books
    approve_jobs(scanned, approved, ids=[1, 2])
    approved.update(row_id=2, status="Applied")
    res = withdraw_jobs(scanned, approved, [1, 2])
    assert res == {"withdrawn": [1], "refused": [2]}
    assert statuses(approved)[1] == "Withdrawn" and statuses(scanned)[1] == "New"
    assert approved.pending(statuses=("Approved",)) == []
    back = approve_jobs(scanned, approved, ids=[1])
    assert [r["ID"] for r in back["approved"]] == [1] and len(approved.rows()) == 2   # revived, not duplicated
    assert statuses(approved)[1] == "Approved" and statuses(scanned)[1] == "Approved"


def test_update_many_single_save_and_append_note(books):
    scanned, _ = books
    n = scanned.update_many([({"row_id": 1}, {"Status": "Shortlisted"}, "first"), ({"row_id": 2}, {"Status": "Shortlisted"}, None),
                             ({"row_id": 99}, {"Status": "Shortlisted"}, None)])
    assert n == 2
    scanned.update(row_id=1, append_note="second")
    assert next(r for r in scanned.rows() if r["ID"] == 1)["Notes"] == "first | second"
