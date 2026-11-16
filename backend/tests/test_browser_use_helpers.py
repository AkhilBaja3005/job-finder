import base64
import os

from services.browser_use_helpers import detect_blocker, get_run_timeout, save_review_screenshot


def test_detect_blocker():
    assert detect_blocker("Stuck on a reCAPTCHA challenge") == "captcha"
    assert detect_blocker("Please sign in to continue") == "login"
    assert detect_blocker("Application submitted") is None
    assert detect_blocker("") is None


def test_run_timeout_env(monkeypatch):
    monkeypatch.delenv("BROWSER_USE_TIMEOUT", raising=False)
    assert get_run_timeout(123) == 123
    monkeypatch.setenv("BROWSER_USE_TIMEOUT", "45")
    assert get_run_timeout() == 45
    monkeypatch.setenv("BROWSER_USE_TIMEOUT", "junk")
    assert get_run_timeout(7) == 7
    monkeypatch.setenv("BROWSER_USE_TIMEOUT", "-5")
    assert get_run_timeout(7) == 7


class _History:
    def screenshot_paths(self):
        return []

    def screenshots(self):
        return [base64.b64encode(b"png-bytes").decode()]


def test_save_review_screenshot_writes_last_image(tmp_path):
    path = save_review_screenshot(_History(), "https://jobs.example/1", str(tmp_path))
    assert path and os.path.exists(path)
    assert open(path, "rb").read() == b"png-bytes"


def test_save_review_screenshot_never_raises(tmp_path):
    assert save_review_screenshot(object(), "u", str(tmp_path)) is None
