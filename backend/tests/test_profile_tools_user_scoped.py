"""Cloud profile tools must read and write only the authenticated user's own data."""
import asyncio
import json
import os

import pytest

from job_finder_mcp.tools import profile_tools as pt
from services import session_store

RESUME = {
    "name": "Akhil Baja",
    "email": "a@example.com",
    "phone": "+44 7000 000000",
    "location": "London, UK",
    "links": ["linkedin.com/in/akhilbaja", "https://github.com/akhilbaja3005", "akhilbaja3005.github.io"],
    "summary": "Applied AI/ML engineer.",
    "skills": {"Languages": ["Python", "SQL."], "AI Governance": ["GDPR", "SARIF."]},
    "experience": [
        {"company": "Qualcomm", "role": "Software Engineer", "start_date": "Dec 2024", "end_date": "Aug 2026",
         "technologies": "", "description": ["Built a pipeline."]},
        {"company": "Axis Bank", "role": "Data Scientist", "start_date": "July 2023", "end_date": "Dec 2024",
         "technologies": None, "description": ["Built a RAG assistant."]},
    ],
    "education": [{"institution": "IIT Hyderabad", "degree": "B.Tech"}],
    "projects": [],
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("SPACE_ID", "test/space")
    monkeypatch.setenv("CANDIDATE_PROFILE_PATH", str(tmp_path / "shared_candidate_profile.json"))
    monkeypatch.delenv("JOB_FINDER_USER_TOKEN", raising=False)
    store = {}

    def fake_get(token):
        return store.get(token, {"data": {}, "path": ""})

    def fake_set(token, data, path):
        store[token] = {"data": data, "path": path}
        return {"status": "success"}

    monkeypatch.setattr(session_store, "get_session_data", fake_get)
    monkeypatch.setattr(session_store, "set_session_data", fake_set)
    return store


def test_get_maps_parsed_experience_links_and_skills(cloud):
    cloud["tok"] = {"data": dict(RESUME), "path": ""}
    res = run(pt.handle_get_candidate_profile({"token": "tok"}))
    cand = res["profile"]["candidate"]
    assert [e["company"] for e in cand["work_experience"]] == ["Qualcomm", "Axis Bank"]
    assert cand["work_experience"][0]["timeline"] == "Dec 2024 – Aug 2026"
    assert cand["linkedin"] == "https://linkedin.com/in/akhilbaja"
    assert cand["github"] == "https://github.com/akhilbaja3005"
    assert cand["portfolio"] == "https://akhilbaja3005.github.io"
    assert cand["core_skills"]["Languages"] == ["Python", "SQL"]
    assert cand["core_skills"]["AI Governance"] == ["GDPR", "SARIF"]


def test_cloud_save_without_token_is_rejected_and_writes_nothing(cloud, tmp_path):
    res = run(pt.handle_save_candidate_profile({"name": "X", "email": "x@example.com"}))
    assert res["success"] is False and res["error"] == "UNAUTHENTICATED"
    assert not os.path.exists(tmp_path / "shared_candidate_profile.json")
    assert cloud == {}


def test_cloud_save_updates_only_that_users_session(cloud, tmp_path):
    cloud["alice"] = {"data": dict(RESUME), "path": ""}
    cloud["bob"] = {"data": {"name": "Bob", "email": "bob@example.com"}, "path": ""}
    res = run(pt.handle_save_candidate_profile({
        "token": "alice",
        "linkedin": "https://www.linkedin.com/in/alice",
        "work_experience": [{"company": "Acme", "role": "Engineer", "start_date": "2020", "end_date": "2022",
                             "highlights": ["Did things."]}],
    }))
    assert res["success"] is True
    assert cloud["alice"]["data"]["linkedin"] == "https://www.linkedin.com/in/alice"
    assert cloud["alice"]["data"]["work_experience"][0]["company"] == "Acme"
    assert cloud["alice"]["data"]["experience"][0]["company"] == "Acme"
    assert cloud["alice"]["data"]["name"] == "Akhil Baja"  # untouched fields survive
    assert cloud["bob"]["data"] == {"name": "Bob", "email": "bob@example.com"}
    assert not os.path.exists(tmp_path / "shared_candidate_profile.json")


def test_save_response_never_returns_portal_password(cloud):
    data = dict(RESUME)
    cloud["alice"] = {"data": {"candidate": {"name": "A", "portals_password": "hunter2"}}, "path": ""}
    res = run(pt.handle_save_candidate_profile({"token": "alice", "name": "A"}))
    assert "hunter2" not in json.dumps(res)
    got = run(pt.handle_get_candidate_profile({"token": "alice"}))
    assert "hunter2" not in json.dumps(got)
    assert data  # silence unused


def test_cloud_sync_rebuilds_work_experience_from_stored_resume(cloud):
    stored = dict(RESUME)
    stored["work_experience"] = []
    cloud["alice"] = {"data": stored, "path": ""}
    res = run(pt.handle_sync_candidate_profile_from_resume({"token": "alice", "resume_path": "/Users/me/none.pdf"}))
    assert res["success"] is True and res["experience_count"] == 2
    got = run(pt.handle_get_candidate_profile({"token": "alice"}))["profile"]["candidate"]
    assert [e["company"] for e in got["work_experience"]] == ["Qualcomm", "Axis Bank"]


def test_cloud_sync_without_token_or_resume_fails_cleanly(cloud):
    assert run(pt.handle_sync_candidate_profile_from_resume({}))["error"] == "UNAUTHENTICATED"
    res = run(pt.handle_sync_candidate_profile_from_resume({"token": "nobody"}))
    assert res["success"] is False


def test_clean_skills_strips_trailing_period_but_keeps_inner_dots():
    assert pt.clean_skills(["Python", "SQL.", "Node.js", " MCP. ", ""]) == ["Python", "SQL", "Node.js", "MCP"]
