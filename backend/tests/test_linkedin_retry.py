"""LinkedIn's guest API rate-limits parallel searches (HTTP 429): requests must be capped and retried, not dropped."""

import io
import os
import sys
import threading
import time
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

js = pytest.importorskip("backend.services.job_searcher")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


def test_429_is_retried_with_backoff_then_succeeds(monkeypatch):
    calls, sleeps = [], []

    def fake_urlopen(req, context=None, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise http_error(429)
        return FakeResponse(b"<li>ok</li>")
    monkeypatch.setattr(js.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    assert js._linkedin_get("https://x", {}) == "<li>ok</li>"
    backoffs = [x for x in sleeps if x >= 1.0]                                   # (a 0.3s politeness pause follows the success)
    assert len(calls) == 3 and len(backoffs) == 2 and backoffs[1] > backoffs[0]


def test_a_permanent_error_is_raised_not_retried_forever(monkeypatch):
    calls = []
    monkeypatch.setattr(js.urllib.request, "urlopen", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(http_error(404)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        js._linkedin_get("https://x", {})
    assert len(calls) == 1                                                       # 404 is final: no retry


def test_gives_up_after_the_last_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(js.urllib.request, "urlopen", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(http_error(429)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        js._linkedin_get("https://x", {}, attempts=3)
    assert len(calls) == 3


def test_at_most_three_requests_are_in_flight(monkeypatch):
    inflight, peak, lock = [0], [0], threading.Lock()

    def slow(req, context=None, timeout=None):
        with lock:
            inflight[0] += 1
            peak[0] = max(peak[0], inflight[0])
        time.sleep(0.05)
        with lock:
            inflight[0] -= 1
        return FakeResponse(b"<li></li>")
    monkeypatch.setattr(js.urllib.request, "urlopen", slow)
    threads = [threading.Thread(target=js._linkedin_get, args=("https://x", {})) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] <= 3
