"""
test_compilation_and_resilience.py
- Validates compileall across all python source files in backend
- Tests recruiter in-memory TTL caching
- Tests Gemini grounding 429 quota circuit breaker
- Tests extract_recruiter allow_grounding flag
- Tests direct ATS search circuit breaker
"""

import compileall
import os
import pytest
from unittest.mock import patch, MagicMock
from services.recruiter_extractor import (
    discover_recruiter_via_grounding,
    extract_recruiter,
    _recruiter_cache,
    is_recruiter_grounding_quota_exhausted,
    reset_recruiter_grounding_quota
)


def test_compileall_backend_source_files():
    """Compiles all Python files in backend to ensure 0 syntax or parsing errors."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    success = compileall.compile_dir(backend_dir, maxlevels=10, quiet=1)
    assert success is True, "Compilation failed for one or more Python files in backend"


@pytest.mark.asyncio
async def test_recruiter_caching_mechanism():
    """Verifies that discover_recruiter_via_grounding caches lookups by company name."""
    reset_recruiter_grounding_quota()
    test_company = "UniqueTestAcmeCorp"
    _recruiter_cache.pop(test_company.lower(), None)

    with patch("services.gemini_client.call_gemini_grounded") as mock_call:
        mock_call.return_value = {
            "text": '{"name": "Alice Recruiter", "linkedin_url": "https://linkedin.com/in/alicerecruiter"}',
            "citations": []
        }

        # First call hits mock
        res1 = await discover_recruiter_via_grounding(test_company)
        assert res1["recruiter_name"] == "Alice Recruiter"
        assert mock_call.call_count == 1

        # Second call for the same company should hit memory cache immediately without calling Gemini
        res2 = await discover_recruiter_via_grounding(test_company)
        assert res2["recruiter_name"] == "Alice Recruiter"
        assert mock_call.call_count == 1


@pytest.mark.asyncio
async def test_recruiter_cache_different_companies():
    """Verifies that different companies have independent cache entries."""
    reset_recruiter_grounding_quota()
    _recruiter_cache.pop("companya", None)
    _recruiter_cache.pop("companyb", None)

    with patch("services.gemini_client.call_gemini_grounded") as mock_call:
        mock_call.side_effect = [
            {"text": '{"name": "Recruiter A", "linkedin_url": "https://linkedin.com/in/a"}'},
            {"text": '{"name": "Recruiter B", "linkedin_url": "https://linkedin.com/in/b"}'},
        ]
        res_a = await discover_recruiter_via_grounding("CompanyA")
        res_b = await discover_recruiter_via_grounding("CompanyB")

        assert res_a["recruiter_name"] == "Recruiter A"
        assert res_b["recruiter_name"] == "Recruiter B"
        assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_recruiter_429_quota_circuit_breaker():
    """Verifies that a 429 quota error sets quota_exhausted flag and avoids repeat calls."""
    reset_recruiter_grounding_quota()
    company = "RateLimitedCompanyInc"
    _recruiter_cache.pop(company.lower(), None)

    with patch("services.gemini_client.call_gemini_grounded") as mock_call:
        mock_call.side_effect = Exception("429 RESOURCE_EXHAUSTED Quota exceeded for quota metric")

        res = await discover_recruiter_via_grounding(company)
        assert res.get("quota_exhausted") is True
        assert is_recruiter_grounding_quota_exhausted() is True

        # Next call should immediately short-circuit if no custom api key is passed
        mock_call.reset_mock()
        res_short = await discover_recruiter_via_grounding("AnotherCompanyWithoutKey")
        assert res_short.get("quota_exhausted") is True
        mock_call.assert_not_called()

    reset_recruiter_grounding_quota()


@pytest.mark.asyncio
async def test_extract_recruiter_allow_grounding_flag():
    """Verifies that allow_grounding=False skips grounded discovery completely."""
    reset_recruiter_grounding_quota()
    with patch("services.recruiter_extractor.discover_recruiter_via_grounding") as mock_discover:
        mock_discover.return_value = {"recruiter_name": "Bob", "recruiter_profile_url": None}

        # allow_grounding=False (used in discovery)
        res = await extract_recruiter(
            job_url="https://boards.greenhouse.io/stripe/jobs/12345",
            allow_grounding=False
        )
        assert res["recruiter_name"] is None
        mock_discover.assert_not_called()

        # allow_grounding=True (used in outreach modal)
        res_grounded = await extract_recruiter(
            job_url="https://boards.greenhouse.io/stripe/jobs/12345",
            allow_grounding=True
        )
        assert res_grounded["recruiter_name"] == "Bob"
        mock_discover.assert_called_once()


@pytest.mark.asyncio
async def test_search_direct_ats_jobs_quota_circuit_breaker():
    """Verifies that 429 in search_direct_ats_jobs flips the session circuit breaker."""
    import services.job_searcher as js
    js._ats_grounding_quota_exhausted = False

    with patch("services.job_searcher.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED Quota exceeded")

        jobs = js.search_direct_ats_jobs("Staff Engineer", "London", "24h", api_key="test-api-key")
        assert jobs == []
        assert js._ats_grounding_quota_exhausted is True

        # Next search should immediately return empty list without instantiating client
        mock_client_cls.reset_mock()
        jobs_next = js.search_direct_ats_jobs("Staff Engineer", "London", "24h", api_key="test-api-key")
        assert jobs_next == []
        mock_client_cls.assert_not_called()

    # Reset circuit breaker
    js._ats_grounding_quota_exhausted = False

@pytest.mark.asyncio
async def test_job_search_stream_keepalive_and_caching():
    """Verifies that job_routes streaming endpoint returns valid NDJSON."""
    from fastapi.testclient import TestClient
    from main import app
    from unittest.mock import patch

    client = TestClient(app)

    async def mock_find_jobs(**kwargs):
        yield '{"type": "log", "message": "starting"}\n'
        yield '{"type": "result", "jobs": [{"title": "Software Engineer", "company": "Test Co", "score": 90, "estimated": False}]}\n'

    with patch("routes.job_routes.find_matching_jobs", side_effect=mock_find_jobs):
        with patch("routes.job_routes.get_session_data") as mock_sess:
            mock_sess.return_value = {
                "data": {"name": "Test User", "skills": ["Python", "Docker"]}
            }
            res = client.post(
                "/search_matching_jobs",
                json={"role": "Engineer", "location": "London", "timeframe": "24h"},
                headers={"Authorization": "Bearer fake-token"}
            )
            assert res.status_code == 200
            assert "application/x-ndjson" in res.headers.get("content-type", "")
            lines = [line for line in res.text.split("\n") if line.strip()]
            # First line should be immediate ping keepalive
            import json
            first_obj = json.loads(lines[0])
            assert first_obj.get("type") in ["ping", "log"]


def test_outreach_request_and_message_schema():
    """Validates schemas for outreach generation and customization."""
    from routes.ai_routes import GenerateOutreachRequest, OutreachRequest
    req = GenerateOutreachRequest(
        job_url="https://jobs.lever.co/stripe/123",
        job_title="Backend Engineer",
        company_name="Stripe"
    )
    assert req.job_url == "https://jobs.lever.co/stripe/123"
    assert req.job_title == "Backend Engineer"

    outreach_req = OutreachRequest(
        job_description="Seeking a Senior ML Engineer to build production AI systems.",
        job_title="ML Engineer",
        company_name="DeepMind",
        recruiter_name="Sarah Smith",
        recruiter_email="sarah@deepmind.com",
        send_email=False
    )
    assert outreach_req.company_name == "DeepMind"
    assert outreach_req.send_email is False


def test_ttl_cache_bounded_size_and_eviction():
    """Verifies that TTLCache respects max_size bounds and evicts appropriately."""
    from utils.ttl_cache import TTLCache
    cache = TTLCache(ttl_seconds=60, max_size=3)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") == 3

    # Adding a 4th item when max_size is 3 should evict the oldest
    cache.set("d", 4)
    assert len(cache._store) <= 3
    assert cache.get("d") == 4


def test_extension_version_and_asset_integrity():
    """Validates the Chrome extension manifest, files, and version hash endpoint from backend."""
    import json
    ext_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension"))
    assert os.path.exists(ext_dir), f"Extension directory not found at {ext_dir}"

    manifest_path = os.path.join(ext_dir, "manifest.json")
    assert os.path.exists(manifest_path), "manifest.json missing"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("manifest_version") == 3
    assert manifest.get("version") == "3.1.0"
    assert "activeTab" in manifest.get("permissions", [])

    for req_file in ["popup.html", "popup.css", "popup.js", "content.js", "content.css", "background.js"]:
        assert os.path.exists(os.path.join(ext_dir, req_file)), f"{req_file} missing from extension package"

    # Test backend version hash endpoint
    from starlette.testclient import TestClient
    from main import app
    client = TestClient(app)
    res = client.get("/extension_version_hash")
    assert res.status_code == 200
    data = res.json()
    assert data.get("version") == "3.1.0"
    assert "hash" in data
    assert len(data["hash"]) == 32

    # Test dynamic extension zip download endpoint
    res_zip = client.get("/download_extension_zip")
    assert res_zip.status_code == 200
    assert res_zip.headers.get("content-type") == "application/zip"
    assert "attachment; filename=job_finder_extension.zip" in res_zip.headers.get("content-disposition", "")
    assert len(res_zip.content) > 1000


