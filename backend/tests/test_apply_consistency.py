"""Acceptance tests for Phase 8: Cover letter & application consistency (tasks 8.1 - 8.4)."""
from __future__ import annotations

import json
from pathlib import Path

from backend.services.apply_consistency import (
    answer_sensitive_field,
    cross_check_application_consistency,
    record_apply_file_hashes,
    verify_cover_letter_against_ledger,
)


def test_at_8_1_cover_letter_ledger_rejects_unsupported_claim():
    source = (
        "Akhil Bajaj. Applied AI/ML Engineer at Acme AI (2023 - Present). "
        "Built 7 LangGraph agents in Python and reduced latency by 40%."
    )
    jd = "Apple Developer Publications. Build developer tools and LLM evaluation."

    good_cl = (
        "Dear Apple team, I am excited about Developer Publications. "
        "At Acme AI, I built 7 LangGraph agents in Python and reduced latency by 40%."
    )
    res_ok = verify_cover_letter_against_ledger(good_cl, source_text=source, jd_text=jd)
    assert res_ok["ok"], res_ok

    bad_cl = (
        "Dear Apple team, at Acme AI I managed 25 engineers in Kubernetes "
        "and boosted revenue by 300%."
    )
    res_bad = verify_cover_letter_against_ledger(bad_cl, source_text=source, jd_text=jd)
    assert not res_bad["ok"]
    assert res_bad["issues"]


def test_at_8_2_cross_check_catches_title_date_number_mismatch():
    cv_data = {
        "roles": [{"title": "Applied AI/ML Engineer", "company": "Acme AI", "dates": "2023 - Present"}],
        "text": "Reduced latency by 40% using Python and LangGraph.",
    }
    cover_letter = "As Senior Principal Architect at Acme AI, I reduced latency by 60%."
    form_answers = {"current_title": "Applied AI/ML Engineer", "start_date": "2022"}

    mismatches = cross_check_application_consistency(
        cv_data=cv_data,
        cover_letter=cover_letter,
        form_answers=form_answers,
    )
    assert mismatches
    cats = {m["category"] for m in mismatches}
    assert "number_mismatch" in cats or "title_mismatch" in cats


def test_at_8_3_apply_records_and_matches_sha256_hashes(tmp_path: Path):
    cv_pdf = tmp_path / "cv.pdf"
    cl_txt = tmp_path / "cover_letter.txt"
    log_path = tmp_path / "apply_log.json"
    cv_pdf.write_bytes(b"%PDF-1.4 reviewed cv")
    cl_txt.write_text("Reviewed cover letter", encoding="utf-8")

    entry = record_apply_file_hashes(
        log_path=log_path,
        job_id="0016",
        files={"cv_pdf": cv_pdf, "cover_letter": cl_txt},
    )
    assert len(entry["hashes"]["cv_pdf"]) == 64
    assert len(entry["hashes"]["cover_letter"]) == 64

    saved = json.loads(log_path.read_text(encoding="utf-8"))
    assert saved[-1]["job_id"] == "0016"
    assert saved[-1]["hashes"]["cv_pdf"] == entry["hashes"]["cv_pdf"]


def test_at_8_4_sensitive_answers_never_estimated():
    profile = {"work_authorization": "UK Graduate Visa", "notice_period": "1 month"}
    val, missing = answer_sensitive_field("work_authorization", profile)
    assert val == "UK Graduate Visa" and not missing

    sal, missing_sal = answer_sensitive_field("salary_expectation", profile)
    assert sal == ""
    assert "salary_expectation" in missing_sal
