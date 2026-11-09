"""
test_offline_ats_fixtures.py — Tests ATS form autofill parsing against offline mock fixtures.
Validates field classification, reflex extraction, and blocker detection without network calls.
"""

import os
import pytest
from bs4 import BeautifulSoup
from backend.services.laya_router import get_laya_router


@pytest.fixture
def mock_candidate():
    return {
        "candidate": {
            "name": "Akhil Baja",
            "email": "akhilbaja.work@gmail.com",
            "phone": "+44 7123456789",
            "location": "London, UK",
            "linkedin": "https://linkedin.com/in/akhilbaja",
            "github": "https://github.com/AkhilBaja3005",
            "requires_sponsorship": True,
            "gender": "Male",
            "ethnicity": "Asian",
            "veteran_status": "No",
            "disability_status": "No"
        }
    }


def test_greenhouse_mock_fixture_autofill(mock_candidate):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "mock_ats_forms", "greenhouse", "index.html")
    assert os.path.exists(fixture_path), "Greenhouse fixture missing"

    with open(fixture_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    router = get_laya_router()
    inputs = soup.find_all(["input", "select", "textarea"])
    resolved = {}

    for elem in inputs:
        name = elem.get("name") or elem.get("id") or ""
        label_elem = soup.find("label", attrs={"for": elem.get("id")})
        label_text = label_elem.get_text(strip=True) if label_elem else name

        field_type = router.classify_form_field(label_text)
        route_type, val = router.route_decision(label_text, mock_candidate)
        if route_type == "reflex":
            resolved[field_type] = val

    assert resolved.get("first_name") == "Akhil"
    assert resolved.get("last_name") == "Baja"
    assert resolved.get("email") == "akhilbaja.work@gmail.com"
    assert resolved.get("phone") == "+44 7123456789"
    assert resolved.get("country") == "United Kingdom"
    assert resolved.get("linkedin") == "https://linkedin.com/in/akhilbaja"


def test_ashby_mock_fixture_autofill(mock_candidate):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "mock_ats_forms", "ashby", "index.html")
    assert os.path.exists(fixture_path), "Ashby fixture missing"

    with open(fixture_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    router = get_laya_router()
    inputs = soup.find_all(["input", "select", "textarea"])
    assert len(inputs) > 0


def test_blocker_detection(mock_candidate):
    router = get_laya_router()

    route, _ = router.route_decision("Please answer without AI assistance in your own words:", mock_candidate)
    assert route == "blocked_ai_policy"

    route, _ = router.route_decision("I certify under penalty of perjury that all answers are true", mock_candidate)
    assert route == "blocked_legal_sensitive"


def test_openai_decisions_integration(monkeypatch):
    from backend.services.laya_router import call_openai_decisions_api, get_laya_router

    class MockResponse:
        status_code = 200
        def json(self):
            return {
                "model": "gpt-6-luna",
                "answers": [
                    {
                        "name": "field_category",
                        "type": "choice",
                        "choice": "phone_country_code",
                        "probabilities": {"phone_country_code": 0.99},
                        "confidence": 0.99
                    }
                ]
            }

    import requests
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: MockResponse())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-luna")

    answers = call_openai_decisions_api(
        input_text="Select your country prefix flag",
        questions=[{"type": "choice", "name": "field_category", "choices": ["phone_country_code"]}]
    )
    assert answers is not None
    assert answers[0]["choice"] == "phone_country_code"

    router = get_laya_router()
    field = router.classify_form_field("Select your international country calling prefix")
    assert field == "phone_country_code"
