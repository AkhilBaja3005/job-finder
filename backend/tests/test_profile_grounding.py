"""Answers typed into forms must come from the user's data: the resolver, the checker, and the tools."""
import datetime
import json

import pytest

from services import grounding as g
from services.browser_use_tools import GroundingAudit, build_tools, lookup, verify

TODAY = datetime.date(2026, 6, 15)
PROFILE = {"candidate": {
    "name": "Ada Lovelace", "email": "ada@example.com", "phone": "+44 7000 000000", "location": "Leeds, United Kingdom",
    "linkedin": "https://linkedin.com/in/ada", "work_authorization": "Citizen: UK law allows me to work", "requires_sponsorship": False,
    "salary_expectations": "", "gender": "", "veteran_status": "No", "over_18": True,
    "core_skills": ["Python", "SQL", "Docker"],
    "work_experience": [
        {"company": "Qualcomm", "role": "AI Engineer", "timeline": "Jan 2023 - Present", "highlights": ["Built Python pipelines"]},
        {"company": "Axis Bank", "role": "Analyst", "timeline": "Jun 2021 - Dec 2022", "highlights": ["SQL reporting"]},
        {"company": "Overlap Ltd", "role": "Contractor", "timeline": "Jan 2022 - Mar 2022"}],
    "education": [{"institution": "IIT Delhi", "degree": "B.Tech", "field": "Computer Science", "timeline": "2017 - 2021", "cpi": "CPI: 8.4"}]}}


def facts(saved=None):
    return g.ProfileFacts(PROFILE, saved, today=TODAY)


def test_spans_and_months():
    assert g.parse_span("Jan 2023 - Present", TODAY) == (2023 * 12 + 1, 2026 * 12 + 6)
    assert g.parse_span("2017 - 2021", TODAY) == (2017 * 12 + 1, 2021 * 12 + 12)
    assert g.parse_span("Jan 2030 - Dec 2031", TODAY) is None and g.parse_span("no dates", TODAY) is None
    assert g.merge_months([(0, 10), (5, 12), (20, 25)]) == 17
    assert g.years_phrase(27) == "2 years 3 months" and g.years_phrase(12) == "1 year" and g.years_phrase(0) == "less than a month"


def test_total_experience_counts_overlaps_once():
    out = facts().answer("How many years of experience do you have?")
    assert out["status"] == "answer" and out["answer"] == "4" and "4 years 11 months" in out["note"]


def test_skill_years_come_from_roles_that_mention_the_skill():
    assert facts().answer("Years of experience with Python?")["answer"] == "3"
    assert facts().answer("Years of experience with Kubernetes?")["status"] == "no_data"


def test_missing_skill_is_never_answered_no():
    out = facts().answer("Do you have experience with Kubernetes?")
    assert out["status"] == "no_data" and out["answer"] is None and "not answered No" in out["note"]
    assert facts().answer("Do you have experience with Docker?")["answer"] == "Yes"


@pytest.mark.parametrize("question,expected", [
    ("First name", "Ada"), ("Last Name", "Lovelace"), ("Email address", "ada@example.com"), ("Mobile phone", "+44 7000 000000"),
    ("LinkedIn profile", "https://linkedin.com/in/ada"), ("Will you now or in the future require visa sponsorship?", "No"),
    ("Are you legally authorized to work in the UK?", "Yes"), ("Are you over 18 years of age?", "Yes"),
    ("Current employer", "Qualcomm"), ("Current job title", "AI Engineer"), ("Are you currently employed?", "Yes"),
    ("Highest degree", "B.Tech"), ("University", "IIT Delhi"), ("Major", "Computer Science"), ("GPA", "8.4"),
    ("Veteran status", "No"),
])
def test_standard_questions_resolve_from_the_profile(question, expected):
    out = facts().answer(question)
    assert out["status"] == "answer" and out["answer"] == expected, out


def test_policy_answers_when_the_user_gave_none():
    sal = facts().answer("Salary expectations")
    assert sal["status"] == "policy" and not any(ch.isdigit() for ch in sal["answer"])
    gender = facts().answer("Gender")
    assert gender["status"] == "policy" and gender["answer"] == g.PREFER_NOT
    assert facts().answer("How did you hear about us?")["status"] == "policy"


def test_only_the_user_can_answer_legal_questions():
    f = g.ProfileFacts({"candidate": {"name": "Ada"}}, today=TODAY)
    assert f.answer("Are you over 18?")["status"] == "stop"
    assert f.answer("Do you consent to a background check?")["status"] == "stop"


def test_worked_here_before_uses_only_the_work_history():
    f = facts()
    assert f.answer("Have you previously worked for Qualcomm?", company="Qualcomm Inc")["answer"] == "Yes"
    assert f.answer("Have you ever worked for this company before?", company="Google")["answer"] == "No"
    assert f.answer("Have you ever worked for this company before?")["status"] == "no_data"


def test_open_ended_gets_facts_to_write_from_and_nothing_else():
    out = facts().answer("Why do you want to work here?")
    assert out["status"] == "compose" and out["facts"]["roles"][0]["company"] == "Qualcomm" and "ONLY" in out["note"]


def test_unknown_questions_have_no_data():
    assert facts().answer("What is your favourite colour?")["status"] == "no_data"


def test_saved_answers_beat_gaps_and_drafts():
    saved = [{"question": "Why do you want to work at a startup?", "answer": "I like owning outcomes."}]
    f = facts(saved)
    assert f.answer("Why do you want to work at a startup?")["source"] == "saved_answers"
    assert f.answer("Your favourite colour")["status"] == "no_data"


def test_options_are_matched_never_invented():
    f = facts()
    assert f.answer("Gender", ["Male", "Female", "Decline to self-identify"])["option"] == "Decline to self-identify"
    assert f.answer("Are you authorized to work in the UK?", ["Yes", "No"])["option"] == "Yes"
    out = f.answer("Highest degree", ["High school", "PhD"])
    assert out["option"] is None and "None of the listed options" in out["note"]
    assert g.pick_option("No", ["Yes, I do", "No, I do not"]) == "No, I do not"
    assert g.pick_option("", ["a"]) is None and g.pick_option("x", []) is None


def test_checker_flags_invented_numbers_companies_and_wrong_facts():
    f = facts()
    bad = f.check([
        {"question": "Years of experience with Python?", "answer": "7"},
        {"question": "Do you need sponsorship?", "answer": "Yes"},
        {"question": "Why do you want this job?", "answer": "I led a team of 40 engineers at Google."},
        {"question": "Do you consent to a background check?", "answer": "Yes"},
    ])
    assert len(bad) == 4, bad
    good = f.check([
        {"question": "Years of experience with Python?", "answer": "3"},
        {"question": "Do you need sponsorship?", "answer": "No"},
        {"question": "Why do you want this job?", "answer": "I built Python pipelines at Qualcomm."},
        {"question": "Gender", "answer": "Prefer not to say"},
        {"question": "Salary", "answer": "Open to discussion"},
        {"question": "Anything else?", "answer": ""},
    ])
    assert good == []


def test_tools_record_an_audit_and_verify_blocks_bad_answers():
    f, audit = facts(), GroundingAudit()
    assert json.loads(lookup(f, audit, "First name"))["answer"] == "Ada"
    assert json.loads(lookup(f, audit, "Favourite colour"))["status"] == "no_data"
    lookup(g.ProfileFacts({"candidate": {"name": "Ada"}}, today=TODAY), audit, "Are you over 18?")
    assert audit.from_profile and audit.no_data == ["Favourite colour"] and len(audit.stopped) == 1 and audit.needs_review
    assert verify(f, audit, "not json").startswith("Could not")
    assert verify(f, audit, {"a": 1}).startswith("Send")
    assert verify(f, audit, [{"question": "Years of experience with Python?", "answer": "9"}]).startswith("NOT OK")
    assert verify(f, GroundingAudit(), json.dumps([{"question": "First name", "answer": "Ada"}])).startswith("OK")
    assert audit.verified and audit.ungrounded and audit.summary()["answered_from_profile"] >= 1


def test_tools_build_when_browser_use_is_present():
    pytest.importorskip("browser_use")
    assert build_tools(facts(), GroundingAudit()) is not None


def test_prompt_no_longer_tells_the_model_to_estimate_or_write_letters():
    from services.browser_use_agent import build_application_task_prompt
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada"})
    assert "truthful estimates" not in prompt and "compelling 3-paragraph" not in prompt
    assert "GROUNDING" in prompt and "profile_answer" in prompt and "verify_answers" in prompt


def test_grounding_setup_returns_an_audit_and_kwargs():
    from services.browser_use_agent import _grounding_setup
    audit, kwargs = _grounding_setup(PROFILE)
    audit.ungrounded.append({"question": "q", "answer": "a", "problem": "p"})
    assert audit.needs_review and isinstance(kwargs, dict)
