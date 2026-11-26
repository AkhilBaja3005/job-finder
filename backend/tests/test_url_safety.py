import socket
import urllib.request
import pytest
from utils import url_safety as us


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:8000/admin", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/", "http://[::1]/", "http://0.0.0.0/",
    "http://100.64.1.1/", "http://metadata.google.internal/", "http://printer.local/", "http://[::ffff:127.0.0.1]/",
    "file:///etc/passwd", "ftp://example.com/", "gopher://x/", "javascript:alert(1)", "http://user:pw@example.com/", "",
])
def test_internal_and_odd_urls_are_refused(url):
    assert us.is_public_http_url(url)[0] is False


def test_public_url_is_allowed(monkeypatch):
    us._host_is_public.cache_clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert us.is_public_http_url("https://boards.greenhouse.io/acme/jobs/1") == (True, "")


def test_name_that_resolves_to_private_ip_is_refused(monkeypatch):
    us._host_is_public.cache_clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    ok, why = us.is_public_http_url("https://evil.example.com/")
    assert ok is False and "private" in why


def test_unresolvable_host_is_refused(monkeypatch):
    us._host_is_public.cache_clear()
    def boom(*a, **k):
        raise OSError("no dns")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert us.is_public_http_url("https://nope.invalid/")[0] is False


def test_redirect_to_internal_address_is_refused():
    import http.client
    import io
    handler = us._CheckedRedirects()
    req = urllib.request.Request("https://example.com/")
    with pytest.raises(us.UnsafeURLError):
        handler.redirect_request(req, io.BytesIO(b""), 302, "Found", http.client.HTTPMessage(), "http://169.254.169.254/latest/meta-data/")


def test_preflight_refuses_internal_url():
    from services.browser_use_agent import preflight_check_job_url
    url, active, reason = preflight_check_job_url("http://169.254.169.254/latest/meta-data/")
    assert active is False and "not allowed" in (reason or "")


@pytest.mark.asyncio
async def test_scraper_refuses_internal_url():
    from services.scraper import scrape_job_description
    res = await scrape_job_description("http://localhost:8000/admin")
    assert res["description"] == "" and "not allowed" in res["error"]


def test_domain_guard_uses_only_supported_fields(monkeypatch):
    from services.browser_use_agent import _domain_guard_kwargs

    class Old:  # an older browser-use without the domain options
        def __init__(self, cdp_url=None): ...

    class New:
        def __init__(self, cdp_url=None, allowed_domains=None, prohibited_domains=None): ...

    monkeypatch.delenv("BROWSER_USE_ALLOWED_DOMAINS", raising=False)
    assert _domain_guard_kwargs(Old) == {}
    guard = _domain_guard_kwargs(New)
    assert "169.254.169.254" in guard["prohibited_domains"] and "allowed_domains" not in guard
    monkeypatch.setenv("BROWSER_USE_ALLOWED_DOMAINS", "*.greenhouse.io, *.lever.co")
    assert _domain_guard_kwargs(New) == {"allowed_domains": ["*.greenhouse.io", "*.lever.co"]}
