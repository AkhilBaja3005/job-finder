import pytest
import os
import sys
import time
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import app
from routes.auth_routes import _CONTACT_RATE_LIMIT, CONTACT_MAX_PER_WINDOW
from services.obscura_scraper import is_obscura_available, get_obscura_binary

client = TestClient(app)

def test_obscura_binary_detection():
    """Verify obscura binary detection and fallback mechanism."""
    binary = get_obscura_binary()
    available = is_obscura_available()
    # On this mac environment ~/.obscura/bin/obscura exists and should be detected
    if binary:
        assert os.path.exists(binary)
        assert available is True
    else:
        # Fallback graceful behavior
        assert available is False

def test_google_oauth_redirect_to_state():
    """Verify Google OAuth URL generates state parameter preserving destination."""
    res = client.get("/auth/url?redirect_to=/platform")
    assert res.status_code == 200
    data = res.json()
    assert "url" in data
    # State should contain /platform
    assert "state=%2Fplatform" in data["url"] or "state=/platform" in data["url"]

def test_google_oauth_callback_redirects_to_state():
    """Verify callback honors the state parameter and defaults to /platform."""
    # Test with custom redirect state
    from unittest.mock import patch
    with patch("routes.auth_routes.exchange_google_code_for_email", return_value=("testuser@example.com", None)), \
         patch("routes.auth_routes.create_or_get_user", return_value={"id": 999}), \
         patch("routes.auth_routes.create_session", return_value="mock_jwt_token"):
        
        # Scenario 1: State specifies /platform
        res = client.get("/auth/callback?code=mock_code&state=/platform", follow_redirects=False)
        assert res.status_code == 307 or res.status_code == 302
        loc = res.headers["location"]
        assert "/platform?token=mock_jwt_token" in loc

        # Scenario 2: No state provided -> defaults to /platform
        res2 = client.get("/auth/callback?code=mock_code", follow_redirects=False)
        assert res2.status_code == 307 or res2.status_code == 302
        loc2 = res2.headers["location"]
        assert "/platform?token=mock_jwt_token" in loc2

def test_contact_rate_limiting():
    """Verify IP rate limiting on /contact endpoint (max 3 submissions / 10 mins)."""
    _CONTACT_RATE_LIMIT.clear()
    headers = {"x-forwarded-for": "203.0.113.195"}
    payload = {
        "name": "Rate Limit Tester",
        "email": "tester@example.com",
        "message": "Testing the submission rate limit."
    }

    # First 3 submissions should succeed
    for i in range(CONTACT_MAX_PER_WINDOW):
        res = client.post("/contact", json=payload, headers=headers)
        assert res.status_code == 200, f"Attempt {i+1} failed unexpectedly: {res.text}"

    # 4th submission within 10 min window MUST trigger 429 Too Many Requests
    blocked_res = client.post("/contact", json=payload, headers=headers)
    assert blocked_res.status_code == 429
    assert "Too many contact submissions" in blocked_res.json()["detail"]
