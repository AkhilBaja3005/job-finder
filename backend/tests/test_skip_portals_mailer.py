import os
import sys
import unittest
import asyncio
import json
from unittest.mock import AsyncMock, patch

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.cron_scheduler import process_and_send_user_digest


class TestSkipPortalsMailer(unittest.IsolatedAsyncioTestCase):

    async def test_process_and_send_user_digest_respects_skip_portals(self):
        test_user = {
            "id": "test_user_123",
            "email": "test@example.com",
            "cron_role": "AI Engineer",
            "cron_location": "London, UK",
            "skip_portals": ["targetjobs", "reed"]
        }

        mock_chunks = [
            json.dumps({
                "type": "result",
                "jobs": [
                    {"title": "AI Engineer", "company": "DeepMind", "score": 90, "url": "https://example.com/job1"}
                ]
            })
        ]

        captured_kwargs = {}

        async def fake_find_matching_jobs(*args, **kwargs):
            captured_kwargs.update(kwargs)
            for chunk in mock_chunks:
                yield chunk

        with patch("services.job_searcher.find_matching_jobs", side_effect=fake_find_matching_jobs), \
             patch("services.cron_scheduler._is_local_deployment", return_value=False), \
             patch("services.cron_scheduler.async_send_notification_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            success = await process_and_send_user_digest(test_user, bypass_time_check=True)
            self.assertTrue(success)
            self.assertIn("exclude_portals", captured_kwargs)
            self.assertIn("targetjobs", captured_kwargs["exclude_portals"])
            self.assertIn("reed", captured_kwargs["exclude_portals"])
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            self.assertEqual(call_kwargs["to_email"], "test@example.com")
            self.assertIn("DeepMind", call_kwargs["html_body"])

    async def test_process_and_send_user_digest_profile_skip_portals(self):
        test_user = {
            "id": "test_user_456",
            "email": "profile_test@example.com",
            "cron_role": "Machine Learning Engineer",
            "cron_location": "London, UK"
        }

        mock_profile = {
            "candidate": {"name": "Test User", "email": "profile_test@example.com"},
            "search_preferences": {
                "skip_portals": ["targetjobs"]
            }
        }

        captured_exclude = []

        async def fake_find_matching_jobs(*args, **kwargs):
            captured_exclude.extend(kwargs.get("exclude_portals") or [])
            yield json.dumps({"type": "result", "jobs": []})

        with patch("mcp.tools.profile_tools.load_profile_data", return_value=mock_profile), \
             patch("services.job_searcher.find_matching_jobs", side_effect=fake_find_matching_jobs), \
             patch("services.cron_scheduler._is_local_deployment", return_value=False), \
             patch("services.cron_scheduler.async_send_notification_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await process_and_send_user_digest(test_user, bypass_time_check=True)
            self.assertIn("targetjobs", captured_exclude)


if __name__ == "__main__":
    unittest.main()
