"""LaTeX CV in the app: generation, compile + fit, preview images, claim warnings, and the Api methods."""
import json
import shutil
from pathlib import Path

import pytest

from backend.services import cv_latex, pdf_preview

CV = {
    "name": "Ada Lovelace", "email": "ada@example.org", "phone": "+44 7700 900123", "links": ["https://github.com/ada/graphite"],
    "summary": "Applied AI/ML engineer with 3+ years of experience, systems used by 1,000+ engineers.",
    "experience": [{"company": "Acme", "role": "Engineer", "start_date": "Jan 2022", "end_date": "Dec 2024", "technologies": "Python",
                    "description": ["Built a RAG assistant for 1,300+ employees, cutting support time by 70%."]}],
    "education": [{"institution": "IIT", "degree": "B.Tech", "start_date": "Aug 2019", "graduation_date": "May 2023",
                   "grade": "CPI: 8.04 / 10.0", "highlights": ["Placement Cell Coordinator: led outreach to 100+ firms."]}],
    "projects": [{"title": "Graphite", "technologies": ["Python"], "url": "https://github.com/ada/graphite", "description": ["Built an auditor."]}],
    "skills": ["Python", "RAG"], "skill_groups": {"Languages": ["Python"], "AI/ML & GenAI": ["RAG"]},
}


def test_cv_to_latex_keeps_cpi_highlights_groups_and_escapes():
    cv = json.loads(json.dumps(CV))
    cv["experience"][0]["description"] = ["Cut costs by 40% & raised NPS #1 for R&D_team."]
    tex = cv_latex.cv_to_latex(cv)
    assert "\\documentclass" in tex and "\\begin{document}" in tex
    assert "CPI: 8.04 / 10.0" in tex and "Placement Cell Coordinator" in tex
    assert "Languages" in tex and "AI/ML \\& GenAI" in tex
    assert "40\\%" in tex and "\\&" in tex and "R\\&D\\_team" in tex          # special characters are escaped, not dropped
    assert "github.com/ada/graphite" in tex


def test_spacing_scale_and_font_edit_only_the_template_knobs():
    tex = "\\documentclass[11pt]{resume}\n\\def\\sectionskip{\\vspace{0.08em}}\n\\begin{document}\nHi\n\\end{document}"
    assert cv_latex.apply_spacing_scale(tex, 1.0) == tex
    out = cv_latex.apply_spacing_scale(tex, 0.5, 10.0)
    assert "\\vspace{0.04em}" in out and "\\fontsize{10.0pt}{11.6pt}" in out and out.count("\\begin{document}") == 1


def test_error_summary_picks_the_first_real_error():
    log = "note: x\nerror: Undefined control sequence\nl.42 \\oops\nnote: more"
    assert cv_latex.summarize_error(log).startswith("error: Undefined control sequence")
    assert "l.42" in cv_latex.summarize_error(log)
    assert cv_latex.summarize_error("") == "LaTeX failed."


def test_compile_without_tectonic_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(cv_latex, "tectonic_path", lambda: None)
    ok, err = cv_latex.compile_latex("\\begin{document}\\end{document}", str(tmp_path / "x.pdf"))
    assert not ok and "not installed" in err


def test_fit_tightens_step_by_step_until_one_page(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cv_latex, "compile_latex", lambda tex, out, timeout=180: (seen.append(tex) or True, ""))
    pages = iter([3, 2, 2, 1])
    monkeypatch.setattr(pdf_preview, "page_count", lambda p: next(pages))
    ok, err, n, used = cv_latex.compile_fit_one_page("\\documentclass[11pt]{resume}\n\\begin{document}\nx\\end{document}", str(tmp_path / "o.pdf"))
    assert ok and n == 1 and err == "" and len(seen) == 4 and "\\fontsize" in used


def test_fit_reports_when_it_cannot_fit(monkeypatch, tmp_path):
    monkeypatch.setattr(cv_latex, "compile_latex", lambda tex, out, timeout=180: (True, ""))
    monkeypatch.setattr(pdf_preview, "page_count", lambda p: 2)
    ok, err, n, _ = cv_latex.compile_fit_one_page("\\begin{document}\\end{document}", str(tmp_path / "o.pdf"))
    assert ok and n == 2 and "trim a bullet" in err


def test_a_compile_error_stops_the_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(cv_latex, "compile_latex", lambda tex, out, timeout=180: (False, "error: boom"))
    ok, err, n, _ = cv_latex.compile_fit_one_page("\\begin{document}\\end{document}", str(tmp_path / "o.pdf"))
    assert not ok and err == "error: boom" and n is None


def test_claims_not_in_the_resume_are_reported():
    source = "Built a RAG assistant for 1,300+ employees, cutting support time by 70%. Python, RAG."
    assert cv_latex.unsupported_claims("Built a RAG assistant for 1,300+ employees, cutting support time by 70%.", source) == []
    flagged = cv_latex.unsupported_claims("Built a RAG assistant for 9,999+ employees using Kubernetes and Terraform.", source)
    assert any("9,999" in f for f in flagged) and any("Kubernetes" in f for f in flagged)


def _blank_pdf(path):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        w.write(f)


def test_preview_renders_pages_and_measures_fill(tmp_path):
    pytest.importorskip("pypdfium2")
    pdf = tmp_path / "a.pdf"
    _blank_pdf(pdf)
    pages = pdf_preview.render_pages(str(pdf))
    assert len(pages) == 1 and pages[0].startswith("data:image/png;base64,")
    assert pdf_preview.fill_ratio(str(pdf)) == 0.0 and pdf_preview.page_count(str(pdf)) == 1


def test_preview_helpers_do_not_raise_on_bad_files(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    assert pdf_preview.render_pages(str(bad)) == [] and pdf_preview.fill_ratio(str(bad)) is None
    assert pdf_preview.page_count(str(tmp_path / "missing.pdf")) is None


@pytest.mark.skipif(not cv_latex.tectonic_available(), reason="Tectonic is not installed here")
def test_real_compile_of_the_generated_latex(tmp_path):
    ok, err, pages, _ = cv_latex.compile_fit_one_page(cv_latex.cv_to_latex(CV), str(tmp_path / "cv.pdf"))
    assert ok, err
    assert pages == 1 and (tmp_path / "cv.pdf").stat().st_size > 5000


# ── the Api methods ───────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import scan_panel as panel
    monkeypatch.setattr(panel, "GATE_ENABLED", False)
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path / "support"))
    (tmp_path / "support").mkdir()
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "cv.json").write_text(json.dumps(CV))
    (pack / "cv.pdf").write_bytes(b"%PDF-original")
    (pack / "manifest.json").write_text("{}")
    a = panel.Api([sys.executable])
    monkeypatch.setattr(a, "_pack_dir", lambda job_id: pack if str(job_id) == "1" else None, raising=False)
    monkeypatch.setattr(panel.Api, "_ws_env", lambda self, ws: __import__("contextlib").nullcontext(), raising=False)
    return a, pack, panel


def test_api_get_generates_latex_from_cv_json(api):
    a, pack, _ = api
    r = a.get_pack_latex("1")
    assert r["ok"] and r["source"] == "generated" and "\\begin{document}" in r["tex"] and r["pages"] == [] and r["in_use"] is False
    assert a.get_pack_latex("99")["ok"] is False


def test_api_compile_saves_the_edit_and_returns_preview_and_warnings(api, monkeypatch):
    a, pack, _ = api
    import services.cv_latex as cl           # the module the app itself imports
    monkeypatch.setattr(cl, "tectonic_available", lambda: True)

    def fake(tex, out):
        _blank_pdf(out)
        return True, "", 1, tex
    monkeypatch.setattr(cl, "compile_fit_one_page", fake)
    tex = "\\documentclass{resume}\\begin{document}Built it for 9,999 users\\end{document}"
    r = a.compile_pack_latex("1", tex)
    assert r["ok"] and r["page_count"] == 1 and (pack / "cv.tex").read_text() == tex
    assert a.get_pack_latex("1")["source"] == "saved"


def test_api_compile_rejects_junk_and_reports_missing_tectonic(api, monkeypatch):
    a, pack, _ = api
    assert a.compile_pack_latex("1", "hello")["ok"] is False
    import services.cv_latex as cl           # the module the app itself imports
    monkeypatch.setattr(cl, "tectonic_available", lambda: False)
    r = a.compile_pack_latex("1", "\\begin{document}x\\end{document}")
    assert r["ok"] is False and "not installed" in r["error"]


def test_api_use_replaces_cv_pdf_and_marks_the_manifest(api):
    a, pack, _ = api
    assert a.use_pack_latex_pdf("1")["ok"] is False                      # nothing compiled yet
    (pack / "cv_latex.pdf").write_bytes(b"%PDF-latex")
    assert a.use_pack_latex_pdf("1")["ok"]
    assert (pack / "cv.pdf").read_bytes() == b"%PDF-latex"
    man = json.loads((pack / "manifest.json").read_text())
    assert man["cv_source"] == "latex" and man["cv_edited_by_user"] is True
    assert a.get_pack_latex("1")["in_use"] is True


def test_api_reset_discards_edits_but_not_the_cv_pdf(api):
    a, pack, _ = api
    (pack / "cv.tex").write_text("\\begin{document}edited\\end{document}")
    (pack / "cv_latex.pdf").write_bytes(b"%PDF-x")
    r = a.reset_pack_latex("1")
    assert r["ok"] and r["source"] == "generated" and not (pack / "cv.tex").exists() and (pack / "cv.pdf").exists()
