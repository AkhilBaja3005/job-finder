"""
test_slug_harvester.py — Tests for ATS company slug harvester & registry validator.
"""

import os
import pytest
import tempfile
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

try:
    from backend.services.company_slug_harvester import clean_slug
    from backend.services.company_slug_registry import (
        init_db, save_slugs_to_db, update_slug_status, get_active_slugs, RESERVED_WORDS
    )
except ImportError:
    from services.company_slug_harvester import clean_slug
    from services.company_slug_registry import (
        init_db, save_slugs_to_db, update_slug_status, get_active_slugs, RESERVED_WORDS
    )


def test_clean_slug():
    assert clean_slug("stripe") == "stripe"
    assert clean_slug("Stripe/jobs") == ""
    assert clean_slug("api") == ""
    assert clean_slug("assets") == ""
    assert clean_slug("invalid_slug#frag?q=1") == "invalid_slug"
    assert clean_slug("   ") == ""


def test_sqlite_registry_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_slugs.db")
        init_db(db_path)
        
        test_slugs = {
            "ashby": ["stripe", "openai", "api"],
            "greenhouse": ["airbnb", "figma"],
            "lever": ["netflix"]
        }
        
        saved = save_slugs_to_db(test_slugs, db_path=db_path)
        # 'api' is in RESERVED_WORDS, so 5 valid slugs should be saved
        assert saved == 5
        
        # Verify initial active count is 0
        active_before = get_active_slugs(db_path=db_path)
        assert len(active_before["ashby"]) == 0
        assert len(active_before["greenhouse"]) == 0
        
        # Mark openai and airbnb as active
        update_slug_status("ashby", "openai", is_active=True, job_count=12, db_path=db_path)
        update_slug_status("greenhouse", "airbnb", is_active=True, job_count=45, db_path=db_path)
        
        active_after = get_active_slugs(db_path=db_path)
        assert "openai" in active_after["ashby"]
        assert "airbnb" in active_after["greenhouse"]
        assert "stripe" not in active_after["ashby"]


@pytest.mark.asyncio
async def test_validate_slug_endpoint_mocked():
    from unittest.mock import AsyncMock, patch, MagicMock
    try:
        from backend.services.company_slug_registry import validate_slug_endpoint
    except ImportError:
        from services.company_slug_registry import validate_slug_endpoint

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"jobs": [{"id": 1}, {"id": 2}]}
    mock_client.get.return_value = mock_response

    sem = asyncio.Semaphore(5)
    ats, slug, is_active, job_count = await validate_slug_endpoint(mock_client, "ashby", "cohere", sem)
    assert ats == "ashby"
    assert slug == "cohere"
    assert is_active is True
    assert job_count == 2


def test_portal_scanner_integrates_active_slugs():
    try:
        from backend.services.portal_scanner import PortalScanner
        from backend.services.company_slug_registry import update_slug_status, init_db
    except ImportError:
        from services.portal_scanner import PortalScanner
        from services.company_slug_registry import update_slug_status, init_db

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "company_slugs.db")
        init_db(db_path)
        update_slug_status("ashby", "deepmind-partner", is_active=True, job_count=10, db_path=db_path)

        with patch("services.company_slug_registry.get_db_path", return_value=db_path, create=True):
            with patch("backend.services.company_slug_registry.get_db_path", return_value=db_path, create=True):
                scanner = PortalScanner()
                portals = scanner.config.get("portals", {})
                ashby_slugs = [p["company_slug"] for p in portals.get("ashby", [])]
                assert "deepmind-partner" in ashby_slugs
