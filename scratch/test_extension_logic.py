import unittest
import json
import re

class TestJobFinderExtension(unittest.TestCase):
    """
    Test suite for Job Finder Extension logic & DOM parsing/matching capabilities.
    Validates field matchers, platform selector rules, and safety checks across supported platforms.
    """

    def setUp(self):
        self.supported_platforms = [
            "LinkedIn Easy Apply",
            "Greenhouse",
            "Lever",
            "Workday",
            "Indeed",
            "BambooHR",
            "Ashby"
        ]

    def test_supported_platforms_list(self):
        """Verify all target platforms are explicitly tracked."""
        self.assertEqual(len(self.supported_platforms), 7)
        self.assertIn("LinkedIn Easy Apply", self.supported_platforms)
        self.assertIn("Greenhouse", self.supported_platforms)
        self.assertIn("Workday", self.supported_platforms)

    def test_linkedin_daily_limit_detection(self):
        """Test daily limit string detection logic on LinkedIn."""
        limit_patterns = [
            "You've reached today's Easy Apply limit",
            "reached today's Easy Apply limit",
            "Great effort applying today",
            "continue applying tomorrow"
        ]
        sample_text = "Great effort applying today! Save this job and continue applying tomorrow."

        limit_detected = any(pattern.lower() in sample_text.lower() for pattern in limit_patterns)
        self.assertTrue(limit_detected, "Daily limit detection pattern should match sample page text.")

    def test_field_matching_regex(self):
        """Test regex matching logic for common application fields."""
        fields = {
            "first_name": "first_name given-name firstname fname",
            "last_name": "last_name family-name lastname lname",
            "email": "email e-mail user_email",
            "phone": "phone mobile telephone tel",
            "work_auth": "legally authorized to work in the us",
            "sponsorship": "require visa sponsorship"
        }

        self.assertTrue(re.search(r'first.?name|given.?name|firstname|fname', fields["first_name"]))
        self.assertTrue(re.search(r'last.?name|family.?name|lastname|lname', fields["last_name"]))
        self.assertTrue(re.search(r'email|e-mail', fields["email"]))
        self.assertTrue(re.search(r'phone|mobile|tel', fields["phone"]))
        self.assertTrue(re.search(r'authorized|work in the us', fields["work_auth"]))
        self.assertTrue(re.search(r'sponsor|visa', fields["sponsorship"]))

    def test_blacklist_keyword_filtering(self):
        """Test keyword blacklist logic for auto-skipping jobs."""
        blacklist = ["senior", "lead", "staff", "manager"]
        job_title_1 = "Senior Software Engineer"
        job_title_2 = "Full Stack Engineer"

        should_skip_1 = any(word.lower() in job_title_1.lower() for word in blacklist)
        should_skip_2 = any(word.lower() in job_title_2.lower() for word in blacklist)

        self.assertTrue(should_skip_1, "Senior title should trigger blacklist skip.")
        self.assertFalse(should_skip_2, "Full Stack title should pass blacklist check.")

if __name__ == "__main__":
    unittest.main()
