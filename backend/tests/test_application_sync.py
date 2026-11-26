"""POST /applications/sync: add-only upload from the Mac app."""
from starlette.testclient import TestClient

import routes.job_routes as job_routes
from main import app

client = TestClient(app)
ROW = {"job_title": "AI Engineer", "company": "Acme", "job_url": "https://boards.greenhouse.io/acme/jobs/1", "score": 80, "status": "applied"}


def _patch(monkeypatch, user, existing=()):
    async def fake_user(token):
        return user

    recorded = []
    monkeypatch.setattr(job_routes, "async_get_user_by_token", fake_user)
    monkeypatch.setattr(job_routes, "list_applications", lambda token=None: [{"job_url": u} for u in existing])
    monkeypatch.setattr(job_routes, "record_application", lambda token, entry: recorded.append(entry))
    return recorded


def test_rejects_missing_or_unknown_code(monkeypatch):
    _patch(monkeypatch, None)
    assert client.post("/applications/sync", json={"applications": [ROW]}).status_code == 401
    assert client.post("/applications/sync", json={"applications": [ROW]}, headers={"Authorization": "Bearer NOPE"}).status_code == 401


def test_rejects_guests(monkeypatch):
    _patch(monkeypatch, {"id": "guest_abc"})
    assert client.post("/applications/sync", json={"applications": [ROW]}, headers={"Authorization": "Bearer abc"}).status_code == 401


def test_adds_only_new_urls(monkeypatch):
    recorded = _patch(monkeypatch, {"id": 7}, existing=["https://boards.greenhouse.io/acme/jobs/1"])
    new = {**ROW, "job_url": "https://jobs.lever.co/acme/2"}
    r = client.post("/applications/sync", json={"applications": [ROW, new, new]}, headers={"Authorization": "Bearer CODE12"})
    assert r.status_code == 200
    assert r.json() == {"added": 1, "already": 2}
    assert [e["job_url"] for e in recorded] == ["https://jobs.lever.co/acme/2"]


def test_rejects_oversized_batches_and_bad_rows(monkeypatch):
    _patch(monkeypatch, {"id": 7})
    headers = {"Authorization": "Bearer CODE12"}
    too_many = [{**ROW, "job_url": f"https://example.com/jobs/{i}"} for i in range(501)]
    assert client.post("/applications/sync", json={"applications": too_many}, headers=headers).status_code == 422
    assert client.post("/applications/sync", json={"applications": [{**ROW, "score": 900}]}, headers=headers).status_code == 422


def test_status_update_needs_account_and_known_status(monkeypatch):
    changed = []
    _patch(monkeypatch, {"id": 7})
    monkeypatch.setattr(job_routes, "update_application_status", lambda token, url, status: changed.append((url, status)) or True)
    H = {"Authorization": "Bearer CODE12"}
    body = {"job_url": "https://jobs.lever.co/acme/2", "status": "Interview"}
    assert client.post("/applications/status", json=body, headers=H).json() == {"updated": True}
    assert client.post("/applications/status", json={**body, "status": "Hired!!"}, headers=H).status_code == 422
    _patch(monkeypatch, None)
    assert client.post("/applications/status", json=body, headers=H).status_code == 401
    assert changed == [("https://jobs.lever.co/acme/2", "Interview")]
