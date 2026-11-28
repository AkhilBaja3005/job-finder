"""Acceptance tests for Phase 5: Layout, ATS & Rendering (tasks 5.1 - 5.10)."""
from __future__ import annotations

import json
from pathlib import Path

from backend.services.cv_renderer_ats import (
    STANDARD_HEADINGS,
    build_pdf_metadata,
    build_safe_cv_filename,
    fit_layout_with_floor,
    render_ats_html,
    render_with_fallback,
    region_page_rules,
    run_ats_parse_check,
    save_cv_json_respecting_edits,
)


def _sample_cv(bullets_per_role: int = 4) -> dict:
    return {
        "name": "Akhil Bajaj",
        "email": "akhil@example.org",
        "phone": "+44 7700 900123",
        "linkedin": "https://linkedin.com/in/akhilbajaj",
        "summary": "Applied AI/ML engineer with 3+ years building Python and LLM systems.",
        "roles": [
            {
                "title": "Applied AI/ML Engineer",
                "company": "Acme AI",
                "dates": "2023 – Present",
                "bullets": [
                    {"text": f"Built LLM pipeline #{i} in Python reducing latency by {10 + i}%.", "score": 5.0 - i * 0.5}
                    for i in range(bullets_per_role)
                ],
            }
        ],
        "projects": [
            {"name": "Graphite", "description": "7 LangGraph agents with 4 validation gates.", "url": "https://github.com/akhil/graphite"}
        ],
        "skills": {"AI & ML": ["Python", "LLMs", "LangGraph", "RAG"]},
        "education": [{"degree": "MSc AI", "institution": "Imperial College London", "dates": "Sept 2026 – Sept 2027"}],
    }


def test_at_5_1_and_5_2_font_floor_and_bounded_fill_loop():
    cv = _sample_cv(bullets_per_role=42)
    result = fit_layout_with_floor(cv, page_budget=1, font_floor_pt=9.0, max_iterations=10)
    assert result["font_pt"] >= 9.0
    assert result["iterations"] <= 10
    assert result["pages"] == 1
    assert result["dropped_bullets"] > 0

    cv_small = _sample_cv(bullets_per_role=25)
    res2 = fit_layout_with_floor(cv_small, page_budget=1, font_floor_pt=9.0, max_iterations=10)
    assert res2["font_pt"] >= 9.0
    assert 0.90 <= res2["fill_ratio"] <= 1.0


def test_at_5_3_and_5_4_ats_parse_and_standard_headings():
    for idx in range(3):
        cv = _sample_cv(bullets_per_role=2 + idx)
        html_doc = render_ats_html(cv, region="UK")
        for h in STANDARD_HEADINGS.values():
            assert h in html_doc
        check = run_ats_parse_check(html_doc, expected_name="Akhil Bajaj", expected_email="akhil@example.org")
        assert check["ok"], check


def test_at_5_5_region_rules_a4_vs_letter():
    uk = region_page_rules("UK")
    us = region_page_rules("US")
    assert uk["page_size"] == "A4" and uk["allow_photo"] is False and uk["allow_age"] is False
    assert us["page_size"] == "Letter" and us["allow_photo"] is False


def test_at_5_6_and_5_7_names_personal_details_and_wrapping():
    cv = _sample_cv(bullets_per_role=2)
    cv["name"] = "José-María Álvarez-García 山田太郎"
    cv["phone"] = ""
    cv["linkedin"] = ""
    cv["projects"][0]["url"] = "https://github.com/very-long-org-name/" + "a" * 80
    html_doc = render_ats_html(cv, region="UK")
    assert "José-María" in html_doc
    assert "山田太郎" in html_doc
    assert "hyphens: none" in html_doc or "overflow-wrap: anywhere" in html_doc


def test_at_5_8_pdf_metadata_no_tool_traces():
    meta = build_pdf_metadata(name="Akhil Bajaj", role="Applied ML Engineer", language="en")
    assert meta["Title"] == "Akhil Bajaj - Applied ML Engineer"
    assert meta["Language"] == "en"
    assert "antigravity" not in json.dumps(meta).lower()
    assert "gemini" not in json.dumps(meta).lower()


def test_at_5_9_file_naming_and_respect_user_edits(tmp_path: Path):
    fn = build_safe_cv_filename("Akhil Bajaj", "Acme / AI?", "Applied ML: Engineer*")
    assert fn == "Akhil_Bajaj_Acme_AI_Applied_ML_Engineer.pdf"

    cv_path = tmp_path / "cv.json"
    cv_path.write_text(json.dumps({"edited_by_user": True, "summary": "My manual edit"}))
    written = save_cv_json_respecting_edits(cv_path, {"summary": "Auto"}, redo=False)
    assert written is False
    assert json.loads(cv_path.read_text())["summary"] == "My manual edit"

    written2 = save_cv_json_respecting_edits(cv_path, {"summary": "Auto"}, redo=True)
    assert written2 is True
    assert json.loads(cv_path.read_text())["summary"] == "Auto"


def test_at_5_10_render_fallbacks(tmp_path: Path):
    master_pdf = tmp_path / "master.pdf"
    master_pdf.write_bytes(b"%PDF-1.4 master")
    out_pdf = tmp_path / "out.pdf"

    def _fail_primary(*_a, **_kw):
        raise RuntimeError("Chromium missing")

    def _fail_simple(*_a, **_kw):
        return b""

    res = render_with_fallback(
        "<html><body>CV</body></html>",
        out_pdf,
        primary_renderer=_fail_primary,
        simple_renderer=_fail_simple,
        master_pdf_path=master_pdf,
    )
    assert res["fallback_used"] == "master_pdf"
    assert out_pdf.read_bytes() == b"%PDF-1.4 master"
