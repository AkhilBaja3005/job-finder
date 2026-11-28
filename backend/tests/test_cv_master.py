"""Phase 1 acceptance tests: Source of truth (cv_master.py)."""
from __future__ import annotations

import os
import sys
import time

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from services import cv_master as cm  # noqa: E402


def _base_profile() -> dict:
    return {
        "name": "Ada Lovelace",
        "email": "ada@example.org",
        "phone": "+44 7700 900123",
        "linkedin": "https://linkedin.com/in/adalovelace",
        "experience_summary": "Applied AI/ML engineer with 3+ years building RAG systems.",
        "work_experience": [
            {
                "company": "Acme Bank",
                "role": "Data Scientist",
                "start_date": "Jul 2023",
                "end_date": "Dec 2024",
                "description": [
                    "Built an internal RAG assistant using LLMs and FAISS, cutting resolution time by 70%.",
                ],
            }
        ],
        "education": [
            {"institution": "IIT Hyderabad", "degree": "B.Tech", "start_date": "2019", "graduation_date": "2023"}
        ],
        "projects": [],
        "core_skills": ["Python", "LLMs", "FAISS", "LangGraph"],
    }


def test_11_master_from_real_resume_diffs_missing_profile_items(tmp_path):
    tex = tmp_path / "resume.tex"
    tex.write_text(
        r"""
\section{Education}
IIT Hyderabad — B.Tech | CPI: 8.04 / 10.0
Internship & Placement Cell Coordinator: led outreach to 100+ firms.
\section{Projects}
Graphite: EU AI Act & GDPR Compliance Auditor — Python, LangGraph
Built 7 LangGraph agents behind 4 validation gates.
""",
        encoding="utf-8",
    )
    prof = _base_profile()
    res = cm.diff_resume_and_profile(str(tex), prof)
    missing_joined = " ".join(res["missing_from_profile"]).lower()
    assert "graphite" in missing_joined
    assert "8.04" in missing_joined or "cpi" in missing_joined
    assert "placement" in missing_joined


def test_12_profile_drift_check_warns_when_resume_newer_than_profile(tmp_path):
    resume = tmp_path / "resume.pdf"
    profile = tmp_path / "candidate_profile.json"
    pack = tmp_path / "pack_001"
    pack.mkdir()
    profile.write_text("{}", encoding="utf-8")
    os.utime(profile, (1000, 1000))
    resume.write_bytes(b"%PDF-1.4")
    os.utime(resume, (2000, 2000))
    manifest = pack / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    os.utime(manifest, (500, 500))

    warnings = cm.check_profile_drift(str(resume), str(profile), str(pack))
    assert any("newer" in w.lower() for w in warnings)
    assert any("older" in w.lower() for w in warnings)


def test_13_structured_master_schema_round_trips_three_sample_resumes():
    samples = [
        _base_profile(),
        {
            "name": "Grace Hopper",
            "email": "grace@example.org",
            "work_experience": [],
            "education": [{"institution": "Yale", "degree": "PhD", "start_date": "1930", "graduation_date": "1934", "grade": "Honours"}],
            "projects": [{"title": "COBOL", "technologies": ["Compiler"], "description": ["Designed compiler."]}],
            "publications": ["A Compiler Paper (1952)"],
            "certifications": ["AWS Solutions Architect"],
            "languages": ["English"],
            "core_skills": ["Compiler"],
        },
        {
            "name": "Alan Turing",
            "email": "alan@example.org",
            "work_experience": [{"company": "Bletchley", "role": "Lead Cryptanalyst", "start_date": "1939", "end_date": "1945", "description": ["Built Bombe."]}],
            "awards": ["OBE"],
            "volunteering": ["Math Club"],
            "clearance": "DV",
            "work_authorization": "UK Citizen",
            "core_skills": ["Cryptography"],
        },
    ]
    for s in samples:
        schema = cm.build_structured_master(s)
        assert schema["name"] == s["name"]
        assert "experience" in schema and "education" in schema and "projects" in schema
        assert "certifications" in schema and "awards" in schema and "publications" in schema and "languages" in schema


def test_14_bullet_metadata_is_present_and_stable():
    prof = _base_profile()
    m1 = cm.build_structured_master(prof)
    m2 = cm.build_structured_master(prof)
    meta1 = m1["experience"][0]["bullet_meta"][0]
    meta2 = m2["experience"][0]["bullet_meta"][0]
    assert meta1 == meta2
    assert meta1["has_metric"] is True
    assert "70%" in meta1["metrics"]
    assert "LLMs" in meta1["skills_used"] or "FAISS" in meta1["skills_used"]


def test_15_alias_map_evidence_matching():
    prof = _base_profile()
    prof["projects"] = [{"title": "Graphite", "technologies": ["LangGraph"], "description": ["Built 7 LangGraph agents behind 4 validation gates."]}]
    master = cm.build_structured_master(prof)

    assert cm.has_evidence("Large Language Models", master)["evidenced"] is True
    assert cm.has_evidence("agentic workflows", master)["evidenced"] is True
    assert cm.has_evidence("Kubernetes", master)["evidenced"] is False


def test_16_evidence_snippets_return_exact_source_span():
    prof = _base_profile()
    master = cm.build_structured_master(prof)
    ev = cm.has_evidence("Large Language Models", master)
    assert ev["evidenced"] is True
    assert "LLMs" in ev["snippet"]
    miss = cm.has_evidence("Rust", master)
    assert miss["evidenced"] is False and miss["snippet"] == "no evidence"


def test_17_user_approved_extras_never_auto_add_from_jd():
    prof = _base_profile()
    updated = cm.apply_approved_extras(prof, {"certifications": ["CKA"]}, jd_terms=["Rust", "Swift"])
    assert "CKA" in updated["certifications"]
    joined = str(updated).lower()
    assert "rust" not in joined and "swift" not in joined
