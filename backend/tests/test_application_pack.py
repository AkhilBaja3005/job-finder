"""Offline tests: per-job application packs, the review sign-off, and the apply gate."""

import argparse
import asyncio
import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import application_pack as ap  # noqa: E402
from backend.services import cv_tailor as ct  # noqa: E402
from backend.services.approval import approve_jobs  # noqa: E402
from backend.services.excel_tracker import ExcelTracker, approved_path  # noqa: E402
from tests.test_cv_tailor import JD, PROFILE, plan  # noqa: E402

ROW = {"ID": 7, "Company": "Acme Ltd", "Job Role": "Applied AI Intern", "Location": "London", "ATS %": 91,
       "Job URL": "https://acme.io/jobs/7", "Fit Summary": "Strong agent background.", "Scored By": "AI", "Platform": "Lever"}
JD_COVER = JD + " Please attach a cover letter explaining your interest."


@pytest.fixture
def fake_pdf(monkeypatch):
    """Skip Chromium: write a stub file where a PDF would go (one test below renders for real)."""
    def render(html_text, path):
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 stub")
        return True
    monkeypatch.setattr(ap, "_render_pdf", render)


@pytest.fixture
def fake_llms(monkeypatch):
    calls = {"cover": 0}

    def cover(title, company, jd, candidate):
        calls["cover"] += 1
        return {"status": "success", "cover_letter": f"Dear {company} team,\n\nI build agent systems with LangGraph.\n\nSincerely,\nTest",
                "gaps": "None", "alternative_openings": "Alt opening.", "warnings": []}
    monkeypatch.setattr(ap, "_generate_cover_letter", cover)
    monkeypatch.setattr(ap.fit_scorer, "analyze_fit", lambda *a, **k: (_ for _ in ()).throw(ap.fit_scorer.FitUnavailable("offline")))
    return calls


def build(tmp_path, jd=JD, **kw):
    return ap.build_pack(dict(ROW), PROFILE, jd, base_dir=str(tmp_path / "applications"), llm=lambda p: plan(), **kw)


# ─── the folder ───────────────────────────────────────────────────────────────
def test_folder_name_and_cover_letter_cues():
    assert os.path.basename(ap.pack_folder_for(ROW, "/x")) == "0007_acme-ltd_applied-ai-intern"
    assert ap.needs_cover_letter("Please upload your Cover Letter", "auto") and ap.needs_cover_letter("x", "always")
    assert not ap.needs_cover_letter("Please upload your CV", "auto") and not ap.needs_cover_letter("cover letter", "never")


def test_pack_contains_everything_to_review(tmp_path, fake_pdf, fake_llms):
    res = build(tmp_path)
    names = set(os.listdir(res.folder))
    assert {"REVIEW.md", "job.md", "job_description.txt", "cv.json", "cv.html", "cv.pdf", "cv_changes.md", "manifest.json"} <= names
    assert "cover_letter.txt" not in names and res.cover_letter == "No"                 # the posting does not ask for one
    assert res.status == "Ready for review" and res.cv_tailored
    review = open(os.path.join(res.folder, "REVIEW.md")).read()
    assert "./jf review --ok 7" in review and "cv_changes.md" in review
    assert json.load(open(os.path.join(res.folder, "manifest.json")))["company"] == "Acme Ltd"


def test_cover_letter_only_when_asked_or_forced(tmp_path, fake_pdf, fake_llms):
    res = build(tmp_path, jd=JD_COVER)
    assert res.cover_letter == "Yes" and fake_llms["cover"] == 1
    assert "Dear Acme Ltd team" in open(os.path.join(res.folder, "cover_letter.txt")).read()
    assert {"cover_letter.pdf", "cover_letter_notes.md"} <= set(os.listdir(res.folder))
    forced = build(tmp_path / "b", cover_letter="always")
    assert forced.cover_letter == "Yes"
    never = build(tmp_path / "c", jd=JD_COVER, cover_letter="never")
    assert never.cover_letter == "No"


def test_your_edits_survive_a_rerun_and_redo_discards_them(tmp_path, fake_pdf, fake_llms):
    res = build(tmp_path, jd=JD_COVER)
    cv_path, cl_path = os.path.join(res.folder, "cv.json"), os.path.join(res.folder, "cover_letter.txt")
    cv = json.load(open(cv_path)); cv["summary"] = "MY OWN SUMMARY"; json.dump(cv, open(cv_path, "w"))
    open(cl_path, "w").write("MY OWN LETTER")
    again = build(tmp_path, jd=JD_COVER)
    assert json.load(open(cv_path))["summary"] == "MY OWN SUMMARY" and open(cl_path).read() == "MY OWN LETTER"
    assert fake_llms["cover"] == 1                                                      # no second LLM call
    rendered = build(tmp_path, jd=JD_COVER, render_only=True)
    assert "MY OWN SUMMARY" in open(os.path.join(rendered.folder, "cv.html")).read()
    redo = build(tmp_path, jd=JD_COVER, redo=True)
    assert json.load(open(cv_path))["summary"] != "MY OWN SUMMARY" and fake_llms["cover"] == 2


def test_render_only_needs_an_existing_pack(tmp_path, fake_pdf, fake_llms):
    with pytest.raises(FileNotFoundError):
        build(tmp_path, render_only=True)


def test_no_job_description_means_no_tailoring_and_a_clear_warning(tmp_path, fake_pdf, fake_llms):
    res = build(tmp_path, jd="")
    assert not res.cv_tailored and res.status == "Needs attention" and any("job description" in w.lower() for w in res.warnings)
    assert os.path.isfile(os.path.join(res.folder, "cv.pdf"))                           # still a usable CV (your profile as-is)
    assert "not tailored" in open(os.path.join(res.folder, "cv_changes.md")).read().lower()


def test_html_values_are_escaped(tmp_path):
    cv = ct.master_cv_from_profile(PROFILE)
    cv["summary"] = "Built <script>alert(1)</script> & things"
    html = ap.render_cv_html(cv)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_real_pdf_is_text_based_and_one_page(tmp_path):
    """Renders with real headless Chromium: the PDF must have a text layer an ATS can read."""
    cv = ct.master_cv_from_profile(PROFILE)
    path = str(tmp_path / "cv.pdf")
    try:
        ok = ap._render_pdf(ap.render_cv_html(cv), path)
    except Exception as e:
        pytest.skip(f"Chromium unavailable: {e}")
    if not ok:
        pytest.skip("Chromium unavailable")
    facts = ap.pdf_facts(path)
    assert facts["text_chars"] > 300
    from pypdf import PdfReader
    text = " ".join(p.extract_text() for p in PdfReader(path).pages)
    assert "LangGraph" in text and "Example University" in text and "janedoe" not in text


# ─── workbook + review + apply gate ───────────────────────────────────────────
@pytest.fixture
def books(tmp_path, monkeypatch, fake_pdf, fake_llms):
    monkeypatch.setenv("JOB_FINDER_TRACKER_XLSX", str(tmp_path / "scanned.xlsx"))
    monkeypatch.setenv("JOB_FINDER_APPLICATIONS_DIR", str(tmp_path / "applications"))
    scanned = ExcelTracker()
    approved = ExcelTracker(approved_path(scanned.path))
    scanned.add_jobs([{"Company": "Acme Ltd", "Job Role": "Applied AI Intern", "Location": "London", "ATS %": 91,
                       "Job URL": "https://acme.io/jobs/7", "Status": "New"},
                      {"Company": "Beta", "Job Role": "ML Intern", "Location": "London", "ATS %": 80,
                       "Job URL": "https://beta.io/j/2", "Status": "New"}])
    approve_jobs(scanned, approved, ids=[1, 2])
    return scanned, approved


def test_prepare_records_pack_in_both_workbooks_and_resets_signoff(books, monkeypatch):
    from job_finder.commands import prepare
    scanned, approved = books
    monkeypatch.setattr(prepare, "fetch_descriptions", lambda urls, timeout=45: {u: JD_COVER for u in urls})
    monkeypatch.setattr(ap.cv_tailor, "_default_llm", lambda p: plan())
    results = prepare.prepare_jobs(approved.rows(), scanned, approved, PROFILE, level="intern")
    assert len(results) == 2
    a = {r["ID"]: r for r in approved.rows()}
    assert os.path.isdir(a[1]["Pack Folder"]) and a[1]["Cover Letter"] == "Yes" and a[1]["Docs OK"] == "No"
    assert {r["ID"]: r["Pack Folder"] for r in scanned.rows()}[1] == a[1]["Pack Folder"]


def test_review_signs_off_only_real_packs(books, monkeypatch, capsys):
    from job_finder.commands import prepare, review
    scanned, approved = books
    monkeypatch.setattr(prepare, "fetch_descriptions", lambda urls, timeout=45: {u: JD for u in urls})
    monkeypatch.setattr(ap.cv_tailor, "_default_llm", lambda p: plan())
    prepare.prepare_jobs(approved.rows(), scanned, approved, PROFILE)
    ns = lambda **kw: argparse.Namespace(**{**dict(open=None, ok=None, revoke=None), **kw})  # noqa: E731
    review.run(ns(ok="1,99"))
    st = {r["ID"]: r["Docs OK"] for r in approved.rows()}
    assert st[1] == "Yes" and st[2] == "No"
    review.run(ns(revoke="1"))
    assert {r["ID"]: r["Docs OK"] for r in approved.rows()}[1] == "No"
    os.remove(os.path.join(approved.rows()[1]["Pack Folder"], "cv.pdf"))
    review.run(ns(ok="2"))                                                               # cv.pdf missing: refused
    assert {r["ID"]: r["Docs OK"] for r in approved.rows()}[2] == "No"


def _gate_args(**kw):
    base = dict(target=None, ids=None, min_ats=None, limit=0, company=None, submit=False, yes=True, dry_run=False,
                retry=False, no_pack=False, resume=None, model=None, headless=True, max_steps=5, timeout=10)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def agent(monkeypatch, tmp_path):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    from backend.job_finder_mcp.tools import profile_tools
    resume = tmp_path / "master.pdf"
    resume.write_bytes(b"%PDF master")
    monkeypatch.setattr(profile_tools, "load_profile_data", lambda: {"candidate": PROFILE, "search_preferences": {}})
    monkeypatch.setattr(sc, "find_master_resume_with_mac_tags", lambda: str(resume))
    monkeypatch.setattr(sc, "notify_user_of_applied_applications", lambda *a, **k: True)
    monkeypatch.setattr(sc, "notify_user_of_failed_applications", lambda *a, **k: True)
    state = {"calls": []}

    async def fake(job_url, **kw):
        state["calls"].append({"url": job_url, **kw})
        return {"status": "success", "auto_submit": kw.get("auto_submit"), "final_result": "ok",
                "review_screenshot": None}
    monkeypatch.setattr(sc, "run_browser_use_autofill", fake)
    state["master"] = str(resume)
    return state


def _prepared(books, monkeypatch, jd=JD_COVER):
    from job_finder.commands import prepare
    scanned, approved = books
    monkeypatch.setattr(prepare, "fetch_descriptions", lambda urls, timeout=45: {u: jd for u in urls})
    monkeypatch.setattr(ap.cv_tailor, "_default_llm", lambda p: plan())
    prepare.prepare_jobs(approved.rows(), scanned, approved, PROFILE)
    return scanned, approved


def test_apply_blocks_jobs_until_the_documents_are_signed_off(books, agent, monkeypatch, capsys):
    from job_finder.commands import apply as apply_cmd
    _prepared(books, monkeypatch)
    apply_cmd.run(_gate_args(submit=True))
    assert agent["calls"] == []                                                          # nothing signed off -> nothing opened
    out = capsys.readouterr()
    assert "not signed off" in (out.out + out.err).replace("\n", " ")


def test_apply_uses_the_packs_cv_and_pastes_the_reviewed_cover_letter(books, agent, monkeypatch):
    from job_finder.commands import apply as apply_cmd, review
    scanned, approved = _prepared(books, monkeypatch)
    review.run(argparse.Namespace(open=None, ok="1", revoke=None))
    apply_cmd.run(_gate_args(submit=True))
    assert len(agent["calls"]) == 1                                                       # only the signed-off job
    call = agent["calls"][0]
    folder = {r["ID"]: r["Pack Folder"] for r in approved.rows()}[1]
    assert call["resume_pdf_path"] == os.path.join(folder, "cv.pdf") and call["resume_pdf_path"] != agent["master"]
    assert "Dear Acme Ltd team" in call["cover_letter_text"] and call["cover_letter_path"].endswith("cover_letter.pdf")
    log = open(os.path.join(folder, "apply_log.md")).read()
    assert "SUBMIT -> Applied" in log and "cv.pdf" in log and "pasted from pack" in log
    assert {r["ID"]: r["Status"] for r in approved.rows()}[1] == "Applied"


def test_changing_a_pack_after_signoff_requires_signing_off_again(books, agent, monkeypatch):
    from job_finder.commands import apply as apply_cmd, prepare, review
    scanned, approved = _prepared(books, monkeypatch)
    review.run(argparse.Namespace(open=None, ok="1", revoke=None))
    prepare.prepare_jobs([r for r in approved.rows() if r["ID"] == 1], scanned, approved, PROFILE, render_only=True)
    assert {r["ID"]: r["Docs OK"] for r in approved.rows()}[1] == "No"
    apply_cmd.run(_gate_args(submit=True))
    assert agent["calls"] == []


def test_no_pack_flag_skips_the_gate_and_uses_the_master_resume(books, agent):
    from job_finder.commands import apply as apply_cmd
    apply_cmd.run(_gate_args(no_pack=True, submit=True))                                 # approved, never prepared
    assert len(agent["calls"]) == 2 and {c["resume_pdf_path"] for c in agent["calls"]} == {agent["master"]}
    assert all(c["cover_letter_text"] is None for c in agent["calls"])


def test_approved_but_never_prepared_jobs_are_blocked_with_a_hint(books, agent, capsys):
    from job_finder.commands import apply as apply_cmd
    apply_cmd.run(_gate_args(submit=True))
    out = capsys.readouterr()
    assert agent["calls"] == [] and "no application pack yet" in (out.out + out.err).replace("\n", " ")


def test_cv_is_tightened_step_by_step_until_it_fits_one_page(tmp_path, monkeypatch):
    seen = []

    def render(html_text, path):
        seen.append("font-size:8.9pt" in html_text or "font-size:8.4pt" in html_text)
        open(path, "wb").write(b"%PDF")
        return True
    monkeypatch.setattr(ap, "_render_pdf", render)
    monkeypatch.setattr(ap, "pdf_facts", lambda path: {"pages": 2 if len(seen) < 3 else 1, "text_chars": 999})
    assert ap.render_cv_pdf("<html><style>a{}</style></html>", str(tmp_path / "cv.pdf"))
    assert len(seen) == 3                                    # plain, then two tighter steps; stopped once it fit


def test_a_failed_render_is_reported_not_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "_render_pdf", lambda h, p: False)
    assert ap.render_cv_pdf("<style></style>", str(tmp_path / "cv.pdf")) is False


def test_contact_line_has_no_empty_separators():
    cv = ct.master_cv_from_profile(PROFILE)                     # phone is "Not provided" -> blank
    html = ap.render_cv_html(cv)
    assert "| |" not in html.replace("\n", " ") and "t@example.org | <a" in html
    cv["phone"], cv["links"] = "+44 7000 000000", []
    html = ap.render_cv_html(cv)
    assert "t@example.org | +44 7000 000000" in html and "| </div>" not in html.replace("\n", " ").replace("  ", " ")
