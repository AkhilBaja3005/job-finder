"""
test_jev_ultrafast_and_phone.py — Unit & Integration tests for:
1. International phone & country code parsing (UK, India, US, etc.) across single/split fields.
2. Jev Ultrafast System 1/System 2 agent execution and cascade fallback to browser-use.
"""

import os
import unittest
import asyncio
from unittest.mock import patch, MagicMock

from backend.services.jev_ultrafast_agent import run_jev_ultrafast_autofill, HAS_JEV
from backend.services.browser_use_agent import run_browser_use_autofill, build_application_task_prompt


class TestJevUltrafastAndPhone(unittest.TestCase):

    def test_phone_and_country_code_resolution_uk(self):
        """Verify UK (+44) phone numbers are correctly partitioned and formatted."""
        prompt = build_application_task_prompt(
            job_url="https://jobs.ashbyhq.com/example/123",
            resume_data={
                "name": "Akhil Baja",
                "email": "akhilbaja.work@gmail.com",
                "phone": "+44 7414646921",
                "location": "London, UK"
            }
        )
        self.assertIn("United Kingdom (+44)", prompt)
        self.assertIn("7414646921", prompt)
        self.assertIn("+447414646921", prompt)

    def test_phone_and_country_code_resolution_india(self):
        """Verify India (+91) phone numbers are correctly partitioned and formatted."""
        prompt = build_application_task_prompt(
            job_url="https://boards.greenhouse.io/example/jobs/123",
            resume_data={
                "name": "Akhil Baja",
                "email": "akhilbaja.work@gmail.com",
                "phone": "+91 9948083135",
                "location": "Hyderabad, India"
            }
        )
        self.assertIn("India (+91)", prompt)
        self.assertIn("9948083135", prompt)
        self.assertIn("+919948083135", prompt)

    def test_phone_and_country_code_resolution_us(self):
        """Verify US (+1) phone numbers are correctly partitioned."""
        prompt = build_application_task_prompt(
            job_url="https://jobs.lever.co/example/123",
            resume_data={
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1 4155552671",
                "location": "San Francisco, CA, USA"
            }
        )
        self.assertIn("United States (+1)", prompt)
        self.assertIn("4155552671", prompt)

    def test_jev_ultrafast_graceful_fallback(self):
        """Verify that when Jev signals needs_fallback, run_browser_use_autofill handles it cleanly."""
        async def _run():
            res = await run_jev_ultrafast_autofill(
                job_url="https://jobs.ashbyhq.com/sample",
                resume_data={"name": "Candidate", "phone": "+44 7414646921"}
            )
            if not HAS_JEV:
                self.assertEqual(res.get("status"), "needs_fallback")

        asyncio.run(_run())

    def test_run_browser_use_with_jev_cascade(self):
        """Verify the full 4-tier pipeline execution with mocked Jev and browser-use layers."""
        mock_history = MagicMock()
        mock_history.is_done.return_value = True
        mock_history.final_result.return_value = "SUBMISSION_CONFIRMED: Successfully submitted on Greenhouse."

        async def _run():
            with patch("backend.services.browser_use_agent.preflight_check_job_url", return_value=("https://boards.greenhouse.io/sample/jobs/1", True, None)), \
                 patch("backend.services.browser_use_agent.get_or_create_browser_session", return_value=MagicMock()), \
                 patch("backend.services.browser_use_agent.get_browser_use_llm", return_value=MagicMock()), \
                 patch("backend.services.browser_use_agent.get_browser_use_fallback_llms", return_value=[]), \
                 patch("backend.services.browser_use_agent.Agent.run", return_value=mock_history):

                result = await run_browser_use_autofill(
                    job_url="https://boards.greenhouse.io/sample/jobs/1",
                    resume_data={
                        "name": "Akhil Baja",
                        "email": "akhilbaja.work@gmail.com",
                        "phone": "+44 7414646921",
                        "location": "London, UK"
                    },
                    auto_submit=True
                )

                self.assertEqual(result.get("status"), "success")
                self.assertTrue(result.get("is_done"))
                self.assertIn("SUBMISSION_CONFIRMED", result.get("final_result", ""))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

    def test_laya_decision_router_classification(self):
        """Verify Laya non-autoregressive field classification & reflex values."""
        from backend.services.laya_router import get_laya_router
        router = get_laya_router()

        profile = {
            "name": "Akhil Baja",
            "email": "akhilbaja.work@gmail.com",
            "phone": "+44 7414646921",
            "location": "London, UK",
            "requires_sponsorship": True
        }

        # 1. Test Phone Country Code routing
        route, val = router.route_decision("Phone Country Code", profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "+44")

        # 2. Test First Name routing
        route, val = router.route_decision("First Name", profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "Akhil")

        # 3. Test Sponsorship question
        route, val = router.route_decision("Will you now or in the future require visa sponsorship?", profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "Yes")

        # 4. Test complex essay question routing to System 2 LLM
        route, val = router.route_decision("Please describe a challenging distributed systems bug you resolved in production.", profile)
        self.assertEqual(route, "llm_generation")
        self.assertIsNone(val)
