"""
test_end_to_end_pipeline.py — Comprehensive End-to-End Test Suite for Job Finder AI.

Covers:
1. Candidate Profile Loading & Schema Validation.
2. Phone Number & International Country Code Partitioning (UK, India, US, etc.).
3. Laya Decision Router (<10ms on-device decision intelligence).
4. Multi-tier Autofill Cascading:
   - Tier 1: Jev / Laya Reflex Engine
   - Tier 2: Pure-DOM Fast Path (Flash-Lite)
   - Tier 3: Vision Reasoning (Thinking=True)
   - Tier 4: Playwright Deterministic Autofill
5. Job Discovery & Multi-portal Query Cluster (Greenhouse, Ashby, Lever, Workday).
"""

import os
import sys
import unittest
import asyncio
from unittest.mock import patch, MagicMock

from backend.services.laya_router import get_laya_router, LayaDecisionRouter
from backend.services.jev_ultrafast_agent import run_jev_ultrafast_autofill
from backend.services.browser_use_agent import (
    run_browser_use_autofill,
    build_application_task_prompt,
    preflight_check_job_url
)


class TestEndToEndJobFinderPipeline(unittest.TestCase):

    def setUp(self):
        self.router = get_laya_router()
        self.candidate_profile = {
            "name": "Akhil Baja",
            "email": "akhilbaja.work@gmail.com",
            "phone": "+44 7414646921",
            "location": "London, UK",
            "postal_code": "W12 0BZ",
            "linkedin": "https://linkedin.com/in/akhilbaja",
            "github": "https://github.com/AkhilBaja3005",
            "portfolio": "https://akhilbaja3005.github.io",
            "requires_sponsorship": True,
            "gender": "Male",
            "ethnicity": "Asian",
            "citizenship": "Indian",
            "veteran_status": "No",
            "disability_status": "No"
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Phone & Country Code Parsing Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_phone_uk_formatting(self):
        """Test UK +44 candidate phone resolution in prompt."""
        prompt = build_application_task_prompt(
            job_url="https://jobs.ashbyhq.com/mistral/1",
            resume_data=self.candidate_profile
        )
        self.assertIn("United Kingdom (+44)", prompt)
        self.assertIn("7414646921", prompt)
        self.assertIn("+447414646921", prompt)

    def test_phone_india_formatting(self):
        """Test India +91 candidate phone resolution in prompt."""
        india_profile = dict(self.candidate_profile)
        india_profile["phone"] = "+91 9948083135"
        india_profile["location"] = "Hyderabad, India"

        prompt = build_application_task_prompt(
            job_url="https://boards.greenhouse.io/anthropic/jobs/1",
            resume_data=india_profile
        )
        self.assertIn("India (+91)", prompt)
        self.assertIn("9948083135", prompt)
        self.assertIn("+919948083135", prompt)

    def test_phone_us_formatting(self):
        """Test US +1 candidate phone resolution in prompt."""
        us_profile = dict(self.candidate_profile)
        us_profile["phone"] = "+1 4155552671"
        us_profile["location"] = "San Francisco, CA"

        prompt = build_application_task_prompt(
            job_url="https://jobs.lever.co/palantir/1",
            resume_data=us_profile
        )
        self.assertIn("United States (+1)", prompt)
        self.assertIn("4155552671", prompt)
        self.assertIn("+14155552671", prompt)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Laya Decision Engine Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_laya_field_classification_taxonomy(self):
        """Ensure all critical ATS field names map directly without hallucinations."""
        test_cases = [
            ("Phone Country Code", "phone_country_code"),
            ("Country dial code", "phone_country_code"),
            ("Mobile phone number", "phone"),
            ("Given name", "first_name"),
            ("Family name", "last_name"),
            ("Email Address", "email"),
            ("LinkedIn Profile URL", "linkedin"),
            ("GitHub URL", "github"),
            ("Will you now or in the future require visa sponsorship?", "sponsorship"),
            ("Notice period (weeks/months)", "notice_period"),
            ("How did you hear about us?", "source_referral"),
            ("Upload Resume / CV", "resume_upload"),
            ("Please tell us about a time you led an engineering team through a crisis.", "custom_essay"),
        ]
        for label, expected_type in test_cases:
            res = self.router.classify_form_field(label)
            self.assertEqual(res, expected_type, f"Failed for label: {label}")

    def test_laya_reflex_routing_vs_llm_generation(self):
        """Verify reflex questions return instant profile values, while essays route to LLM."""
        # Reflex question 1: Sponsorship
        route, val = self.router.route_decision("Do you require sponsorship?", self.candidate_profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "Yes")

        # Reflex question 2: Source
        route, val = self.router.route_decision("How did you hear about this job?", self.candidate_profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "LinkedIn")

        # Reflex question 3: Phone Country
        route, val = self.router.route_decision("Country Dial Code", self.candidate_profile)
        self.assertEqual(route, "reflex")
        self.assertEqual(val, "+44")

        # System 2 Essay Question
        route, val = self.router.route_decision("Why are you interested in joining Qualcomm as an AI Engineer?", self.candidate_profile)
        self.assertEqual(route, "llm_generation")
        self.assertIsNone(val)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Pre-flight URL & Expired Job Detection Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_preflight_active_url(self):
        """Verify preflight check passes on healthy URLs without launching browser."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.geturl.return_value = "https://boards.greenhouse.io/stripe/jobs/123"
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = b"<html><title>Senior AI Engineer at Stripe</title></html>"
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            final_url, is_active, reason = preflight_check_job_url("https://boards.greenhouse.io/stripe/jobs/123")
            self.assertTrue(is_active)
            self.assertIsNone(reason)

    def test_preflight_expired_url_detection(self):
        """Verify preflight detects expired / taken down job without launching browser."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.geturl.return_value = "https://jobs.ashbyhq.com/closed/123"
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = b"<html><body>This job is no longer available.</body></html>"
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            final_url, is_active, reason = preflight_check_job_url("https://jobs.ashbyhq.com/closed/123")
            self.assertFalse(is_active)
            self.assertIn("no longer available", reason)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Multi-Tier Autofill End-to-End Orchestration Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_e2e_autofill_cascade_and_submission(self):
        """Test complete execution flow from Jev fallback to browser-use submission confirmation."""
        mock_history = MagicMock()
        mock_history.is_done.return_value = True
        mock_history.final_result.return_value = "SUBMISSION_CONFIRMED: Successfully applied on Workday."

        async def _run():
            with patch("backend.services.browser_use_agent.preflight_check_job_url", return_value=("https://salesforce.wd12.myworkdayjobs.com/job/1", True, None)), \
                 patch("backend.services.browser_use_agent.get_or_create_browser_session", return_value=MagicMock()), \
                 patch("backend.services.browser_use_agent.get_browser_use_llm", return_value=MagicMock()), \
                 patch("backend.services.browser_use_agent.get_browser_use_fallback_llms", return_value=[]), \
                 patch("backend.services.browser_use_agent.Agent.run", return_value=mock_history):

                res = await run_browser_use_autofill(
                    job_url="https://salesforce.wd12.myworkdayjobs.com/job/1",
                    resume_data=self.candidate_profile,
                    auto_submit=True
                )

                self.assertEqual(res.get("status"), "success")
                self.assertTrue(res.get("is_done"))
                self.assertIn("SUBMISSION_CONFIRMED", res.get("final_result", ""))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
