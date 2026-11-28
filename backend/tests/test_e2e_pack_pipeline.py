"""End-to-end integration test for build_pack + Phase 1-10 manifest & HTML output."""
from __future__ import annotations

import json
from pathlib import Path

from backend.services import application_pack


def test_e2e_build_pack_populates_phase_1_to_10_manifest_and_html(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(application_pack, "render_cv_pdf", lambda html_text, path: False)
    monkeypatch.setattr(application_pack, "_fit_md", lambda *a, **kw: "")

    candidate = {
        "name": "Akhil Bajaj",
        "email": "akhil@example.org",
        "phone": "+44 7700 900123",
        "location": "London, UK",
        "summary": "Applied AI/ML engineer with 3+ years building Python, LLM, and LangGraph systems.",
        "work_experience": [
            {
                "role": "Applied AI/ML Engineer",
                "company": "Acme AI",
                "start_date": "2023",
                "end_date": "Present",
                "description": [
                    "Built LLM and RAG evaluation pipelines in Python reducing latency by 40%.",
                    "Deployed FastAPI and Docker services for internal developer tools.",
                ],
            }
        ],
        "projects": [
            {
                "title": "Graphite",
                "description": "7 LangGraph agents with 4 validation gates for agentic workflows.",
                "url": "https://github.com/akhil/graphite",
            }
        ],
        "skills": ["Python", "LLMs", "LangGraph", "RAG", "FastAPI", "Docker"],
        "education": [{"degree": "BTech Computer Science", "institution": "NIT", "dates": "2018 – 2022"}],
    }
    row = {"ID": 16, "Company": "Apple", "Job Role": "Applied Machine Learning Engineer - Developer Publications", "Job URL": "https://jobs.apple.com/16"}
    jd = (
        "About the Role\n"
        "Apple Developer Publications builds ML-powered documentation tooling.\n\n"
        "Required\n"
        "- 3+ years with Python, Large Language Models, agentic workflows, RAG, and FastAPI.\n"
    )

    res = application_pack.build_pack(
        row,
        candidate,
        jd,
        cover_letter="never",
        llm=lambda *_a, **_kw: json.dumps({"summary": candidate["summary"], "skills": candidate["skills"]}),
        base_dir=str(tmp_path),
    )
    manifest = json.loads((Path(res.folder) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tailor_model"]
    assert "lite" not in manifest["tailor_model"].lower()
    assert manifest["cover_letter_status"] == "not_asked"
    found_low = [k.lower() for k in manifest["evidence_panel"]["keywords_found"]]
    assert "large language models" in found_low
    assert "agentic workflows" in found_low
    assert (Path(res.folder) / "cv.html").is_file()
