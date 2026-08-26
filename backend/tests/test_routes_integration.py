import pytest
from starlette.testclient import TestClient
from main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "job-finder-backend"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "job-finder-backend"}


def test_auth_url():
    response = client.get("/auth/url")
    assert response.status_code == 200
    assert "url" in response.json()


def test_answer_question_deterministic_notice():
    response = client.post(
        "/answer_question",
        json={"question": "What is your notice period?", "company_name": "Granola"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Available immediately" in data["answer"]


def test_answer_question_deterministic_salary():
    response = client.post(
        "/answer_question",
        json={"question": "What are your salary expectations?", "company_name": "Granola"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Competitive market rate" in data["answer"]


def test_extension_parse_job_details():
    response = client.post(
        "/extension/parse_job_details",
        json={
            "page_title": "AI Engineer",
            "page_text": "We are looking for an AI Engineer at Granola to work on GenAI systems."
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["job_title"] == "AI Engineer"
    assert data["company"] == "Granola"


def test_get_session_resume_guest():
    response = client.get("/get_session_resume")
    assert response.status_code == 200
    assert "data" in response.json()


def test_applications_endpoint():
    response = client.get("/applications")
    assert response.status_code == 200
    assert "applications" in response.json()
