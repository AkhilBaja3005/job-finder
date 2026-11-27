"""The questions a resume cannot answer, and the places the agent must never guess."""
import json

import pytest

from services import about_you as ay
from services.browser_use_agent import build_application_task_prompt
from services.relevance import check_relevance, level_check, wanted_levels

# The shape of a real profile: seniority says Senior/Staff/Lead while the title filter and the roles ask for interns.
USER_PREFS = {"seniority": ["Senior", "Staff", "Lead"], "target_roles": ["AI Engineer Intern"], "required_title_keywords": ["Intern"], "target_locations": ["London", "Remote"]}


def _profile(tmp_path, candidate=None, prefs=None):
    path = tmp_path / "candidate_profile.json"
    path.write_text(json.dumps({"candidate": candidate if candidate is not None else {"name": "Ada", "email": "ada@example.com", "work_experience": [{"company": "X"}]},
                                "search_preferences": prefs if prefs is not None else {"target_roles": ["AI Engineer Intern"]}}))
    return str(path)


# ── what the user asked for beats the seniority list ─────────────────────────────
def test_interns_are_not_skipped_when_the_roles_and_title_filter_ask_for_interns():
    assert "intern" in wanted_levels(USER_PREFS)
    assert level_check("AI Engineer Intern", USER_PREFS)[0] is True
    assert level_check("Machine Learning Placement Student", USER_PREFS)[0] is True
    assert level_check("Senior ML Engineer", USER_PREFS)[0] is True                    # the listed levels still work
    assert level_check("Head of AI", USER_PREFS)[0] is False                           # a level nobody asked for is still skipped
    assert check_relevance({"title": "Summer AI Intern", "location": "London, UK"}, "", {"requires_sponsorship": False}, USER_PREFS) == (True, "")


def test_no_preference_still_means_no_rule():
    assert wanted_levels({"required_title_keywords": ["Intern"]}) == set()
    assert level_check("Director of Data", {}) == (True, "")


# ── reading and saving the answers ───────────────────────────────────────────────
def test_read_lists_questions_and_what_is_still_unanswered(tmp_path):
    out = ay.read_about_you(_profile(tmp_path))
    assert out["exists"] is True
    keys = [f["key"] for f in out["fields"]]
    assert {"work_authorization", "requires_sponsorship", "notice_period", "salary_expectations", "seniority", "gender", "disability_status"} <= set(keys)
    assert set(out["unanswered"]) == {"work_authorization", "requires_sponsorship", "notice_period", "seniority"}   # the optional ones never block
    assert ay.read_about_you(str(tmp_path / "missing.json")) == {"exists": False, "fields": [], "unanswered": []}


def test_save_writes_into_the_right_sections_and_keeps_everything_else(tmp_path):
    path = _profile(tmp_path)
    ay.save_about_you(path, {"work_authorization": "I need a visa to work (sponsorship)", "requires_sponsorship": "Yes", "notice_period": "1 month",
                             "salary_expectations": " 35,000 to 40,000 GBP ", "seniority": ["Intern", "Junior", "Astronaut"], "disability_status": "Prefer not to say"})
    data = json.load(open(path))
    c, sp = data["candidate"], data["search_preferences"]
    assert c["requires_sponsorship"] is True and c["notice_period"] == "1 month" and c["salary_expectations"] == "35,000 to 40,000 GBP"
    assert c["work_authorization"].startswith("I need a visa") and c["disability_status"] == "Prefer not to say"
    assert sp["seniority"] == ["Intern", "Junior"] and sp["target_roles"] == ["AI Engineer Intern"]     # an invented level is dropped, other settings stay
    assert c["name"] == "Ada" and c["work_experience"] == [{"company": "X"}]
    assert ay.read_about_you(path)["unanswered"] == []
    assert not list(tmp_path.glob("*.tmp"))


def test_false_is_a_real_answer_and_an_empty_optional_answer_removes_the_field(tmp_path):
    path = _profile(tmp_path, candidate={"name": "Ada", "salary_expectations": "50k"})
    ay.save_about_you(path, {"requires_sponsorship": False, "salary_expectations": "  "})
    c = json.load(open(path))["candidate"]
    assert c["requires_sponsorship"] is False and "salary_expectations" not in c


def test_bad_answers_are_refused_and_nothing_is_written(tmp_path):
    path = _profile(tmp_path)
    before = open(path).read()
    for bad in ({"requires_sponsorship": "maybe"}, {"work_authorization": "   "}, {"seniority": []}, {"seniority": "Senior"}, {"notice_period": ""}):
        with pytest.raises(ay.AboutYouError):
            ay.save_about_you(path, bad)
    assert open(path).read() == before
    with pytest.raises(ay.AboutYouError):
        ay.save_about_you(path, "not a dict")


def test_unknown_questions_are_ignored_and_a_missing_profile_is_explained(tmp_path):
    path = _profile(tmp_path)
    out = ay.save_about_you(path, {"portals_password": "hunter2", "user_id": 99, "notice_period": "2 weeks"})
    data = json.load(open(path))["candidate"]
    assert out == {"saved": ["notice_period"]} and "portals_password" not in data and "user_id" not in data
    with pytest.raises(ay.AboutYouError, match="Create your profile"):
        ay.save_about_you(str(tmp_path / "none.json"), {"notice_period": "2 weeks"})


def test_long_answers_are_cut(tmp_path):
    path = _profile(tmp_path)
    ay.save_about_you(path, {"salary_expectations": "x" * 900})
    assert len(json.load(open(path))["candidate"]["salary_expectations"]) == 200


# ── the agent never invents these answers ────────────────────────────────────────
def test_prompt_uses_what_the_user_chose():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada", "candidate": {
        "notice_period": "1 month", "salary_expectations": "35,000 GBP", "gender": "Female", "veteran_status": "No", "disability_status": "Prefer not to say",
        "requires_sponsorship": True}})
    assert "Notice Period / Earliest Availability: 1 month" in prompt and "Salary Expectation (use only when a form asks): 35,000 GBP" in prompt
    assert "Requires Visa Sponsorship: Yes" in prompt


def test_prompt_declines_personal_questions_and_does_not_promise_availability_the_user_never_gave():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada"})
    assert "Protected Veteran Status: Prefer not to say" in prompt and "Disability Status: Prefer not to say" in prompt
    assert "Salary Expectation (use only when a form asks): Open to discussion (negotiable)" in prompt
    assert "Disability Status: No" not in prompt and "Protected Veteran Status: No" not in prompt
