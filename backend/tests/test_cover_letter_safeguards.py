from unittest.mock import patch

from services.cover_letter_generator import (
    build_safe_profile, generate_structured_cover_letter, parse_sections, validate_letter,
)

PROFILE = {
    "candidate": {
        "name": "Jane Doe", "email": "jane@example.com", "phone": "+44 7000 000000",
        "portals_password": "hunter2", "api_key": "secret-key", "location": "London, UK",
        "experience_summary": "Built data pipelines that cut costs by 40%.",
        "core_skills": ["python", "sql"],
        "work_experience": [{"company": "Acme", "role": "Engineer", "description": ["Cut cost by 40%"], "phone": "123"}],
    }
}

GOOD = " ".join(["I built pipelines for Acme and cut costs by 40% using python and sql."] * 24)


def test_safe_profile_excludes_sensitive_fields():
    safe = build_safe_profile(PROFILE)
    blob = str(safe)
    for secret in ("jane@example.com", "+44 7000", "hunter2", "secret-key", "123"):
        assert secret not in blob
    assert safe["name"] == "Jane Doe"
    assert safe["work_experience"][0]["company"] == "Acme"


def test_prompt_never_contains_secrets():
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return "### Cover Letter\n" + GOOD

    with patch("services.cover_letter_generator.generate_content_with_fallback", side_effect=fake):
        generate_structured_cover_letter("Eng", "Beta", "Build things", PROFILE)
    assert "hunter2" not in captured["prompt"] and "jane@example.com" not in captured["prompt"]


def test_validate_flags_problems():
    assert validate_letter(GOOD, str(PROFILE)) == []
    issues = " ".join(validate_letter("Short — letter. I am passionate about 99% growth [Name].", str(PROFILE)))
    assert "Too short" in issues and "cliche" in issues and "dashes" in issues
    assert "placeholder" in issues and "99%" in issues


def test_parse_sections_is_tolerant():
    out = "## 3. Cover Letter:\nHello there\n\n### Gaps & Highlights\nNone\n### alternative opening lines\n1. Hi"
    s = parse_sections(out)
    assert s["cover letter"] == "Hello there" and s["gaps"] == "None" and "Hi" in s["alternative opening lines"]
    assert parse_sections("Just a letter with no headings")["cover letter"] == "Just a letter with no headings"


def test_retry_then_needs_review_or_success():
    calls = []

    def fake(prompt, **kw):
        calls.append(prompt)
        return "### Cover Letter\n" + ("Too short." if len(calls) == 1 else GOOD)

    with patch("services.cover_letter_generator.generate_content_with_fallback", side_effect=fake):
        res = generate_structured_cover_letter("Eng", "Beta", "Build things", PROFILE)
    assert len(calls) == 2 and "FIX THESE PROBLEMS" in calls[1]
    assert res["status"] == "success" and res["warnings"] == []


def test_fallback_uses_only_profile_facts():
    with patch("services.cover_letter_generator.generate_content_with_fallback", side_effect=RuntimeError("down")):
        res = generate_structured_cover_letter("Eng", "Beta", "x", PROFILE)
    assert res["status"] == "fallback" and res["warnings"]
    assert "distributed systems" not in res["cover_letter"] and "Jane Doe" in res["cover_letter"]
