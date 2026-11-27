"""The extra questions (referral, relocation, names, languages, age, background check), the prompt rules for questions only the candidate can
answer, how a run's status is decided, and the log of questions the agent meets."""
import argparse
import json

import pytest

from applications_tracker import outcomes
from job_finder.commands import outcomes as outcomes_command
from services import about_you as ay
from services.browser_use_agent import build_application_task_prompt, decide_status
from services.browser_use_helpers import extract_questions


def _profile(tmp_path, candidate=None):
    path = tmp_path / "candidate_profile.json"
    path.write_text(json.dumps({"candidate": candidate if candidate is not None else {"name": "Ada", "work_experience": [{"company": "Qualcomm"}, {"company": "Axis Bank"}]},
                                "search_preferences": {}}))
    return str(path)


# ── the extra questions ──────────────────────────────────────────────────────────
def test_the_new_questions_are_all_optional_and_in_their_own_sections(tmp_path):
    out = ay.read_about_you(_profile(tmp_path))
    by_key = {f["key"]: f for f in out["fields"]}
    for key in ("referral_source", "relocation", "work_arrangement", "preferred_name", "pronouns", "languages", "over_18", "background_check_consent"):
        assert key in by_key and by_key[key]["required"] is False, key
    assert by_key["referral_source"]["section"] == "Application details" and by_key["over_18"]["section"].startswith("Questions the agent will not answer")
    assert by_key["background_check_consent"]["default"] == "Ask me each time"
    assert not {"referral_source", "over_18", "languages"} & set(out["unanswered"])          # optional ones never block anything


def test_saving_the_new_answers_and_clearing_them(tmp_path):
    path = _profile(tmp_path)
    ay.save_about_you(path, {"referral_source": "LinkedIn", "relocation": "Depends on the role", "work_arrangement": ["Remote", "Hybrid", "Underwater"],
                             "preferred_name": "Addie", "pronouns": "she/her", "languages": "English, Hindi", "over_18": True,
                             "background_check_consent": "Yes, I consent to background checks"})
    c = json.load(open(path))["candidate"]
    assert c["work_arrangement"] == ["Hybrid", "Remote"] and c["over_18"] is True and c["preferred_name"] == "Addie" and c["languages"] == "English, Hindi"
    assert c["background_check_consent"].startswith("Yes")
    ay.save_about_you(path, {"over_18": None, "work_arrangement": [], "preferred_name": "", "relocation": " "})
    c = json.load(open(path))["candidate"]
    assert "over_18" not in c and "work_arrangement" not in c and "preferred_name" not in c and "relocation" not in c    # an empty optional answer is removed
    assert c["referral_source"] == "LinkedIn"                                                                         # others are untouched
    ay.save_about_you(path, {"over_18": False})
    assert json.load(open(path))["candidate"]["over_18"] is False                                                     # No is a real answer


def test_a_required_yes_no_still_cannot_be_left_empty(tmp_path):
    with pytest.raises(ay.AboutYouError, match="Yes or No"):
        ay.save_about_you(_profile(tmp_path), {"requires_sponsorship": None})
    with pytest.raises(ay.AboutYouError, match="Yes or No"):
        ay.save_about_you(_profile(tmp_path), {"requires_sponsorship": ""})


def test_read_cleans_up_a_hand_edited_profile(tmp_path):
    path = _profile(tmp_path, candidate={"work_arrangement": "Remote", "name": "Ada"})        # a string where a list belongs
    fields = {f["key"]: f for f in ay.read_about_you(path)["fields"]}
    assert fields["work_arrangement"]["value"] == []
    assert ay.read_about_you(str(tmp_path / "nope.json"))["exists"] is False
    (tmp_path / "bad.json").write_text("[1, 2]")
    assert ay.read_about_you(str(tmp_path / "bad.json"))["exists"] is False


# ── the prompt ───────────────────────────────────────────────────────────────────
def test_prompt_lists_what_the_user_chose():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada", "candidate": {
        "referral_source": "Indeed", "relocation": "Yes, open to relocating", "work_arrangement": ["Hybrid"], "preferred_name": "Addie",
        "pronouns": "she/her", "languages": "English", "over_18": True, "background_check_consent": "Yes, I consent to background checks",
        "work_experience": [{"company": "Qualcomm"}, {"company": "Axis Bank"}, {"role": "no company"}, "junk"]}})
    for needle in ("Source: Indeed", "Willing to relocate: Yes, open to relocating", "Preferred work arrangement: Hybrid", "Preferred name: Addie",
                   "Pronouns: she/her", "Languages: English", "any age check: answer Yes.", "criminal record check: the candidate consents: answer Yes",
                   "one of: Qualcomm, Axis Bank. Otherwise No."):
        assert needle in prompt, needle


def test_prompt_never_answers_age_or_background_checks_for_the_user():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada"})
    assert "any age check: NOT PROVIDED: stop and report it, do not answer" in prompt
    assert "criminal record check: NOT PROVIDED: stop and report it, do not tick or answer" in prompt
    assert "one of: none listed. Otherwise No." in prompt
    assert "starts with 'BLOCKED:'" in prompt and "Source: the site where you found this job" in prompt
    assert "Willing to relocate: not specified" in prompt
    assert "Ask me each time" not in prompt


def test_age_no_is_answered_no_and_ask_each_time_stops():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada", "candidate": {"over_18": False, "background_check_consent": "Ask me each time"}})
    assert "any age check: answer No." in prompt and "criminal record check: NOT PROVIDED" in prompt


def test_prompt_asks_for_the_question_list_and_acknowledgement_boxes_are_allowed():
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada"})
    assert "starts with 'QUESTIONS:'" in prompt and "at most 25" in prompt
    assert "Privacy notice or terms checkboxes that are required to submit: tick them" in prompt


# ── how a run's status is decided ────────────────────────────────────────────────
@pytest.mark.parametrize("auto,done,blocker,confirmed,failed,denied,blocked,expected", [
    (True, True, None, True, False, False, False, "success"),
    (True, True, None, True, False, True, False, "needs_review"),       # said "not submitted"
    (True, True, None, True, False, False, True, "needs_review"),       # BLOCKED: even with a confirmation word in the text
    (True, True, "captcha", True, False, False, False, "needs_review"),
    (True, False, None, False, True, False, False, "failed"),
    (True, False, None, False, False, False, False, "failed"),          # never finished
    (True, True, None, False, False, False, False, "needs_review"),     # finished but nothing confirmed
    (False, True, None, False, False, True, False, "preview_ready"),    # a practice run says "not submitted" and that is fine
    (False, True, None, False, False, False, False, "preview_ready"),
    (False, True, None, False, False, False, True, "needs_review"),     # a practice run that hit a question only the user can answer
    (False, True, "login", False, False, False, False, "needs_review"),
    (False, False, None, False, False, False, False, "failed"),
])
def test_status_decision_table(auto, done, blocker, confirmed, failed, denied, blocked, expected):
    assert decide_status(auto, done, blocker, confirmed, failed, denied, blocked) == expected


# ── the question log ─────────────────────────────────────────────────────────────
def test_questions_are_read_from_the_last_questions_line():
    text = "Done.\nQUESTIONS: ignore me\nmore text\nQUESTIONS: Are you authorised to work in the UK? | Salary expectation* | Notice period | notice period | x | How did you hear about us?\n"
    assert extract_questions(text) == ["Are you authorised to work in the UK?", "Salary expectation", "Notice period", "How did you hear about us?"]


def test_question_extraction_never_raises_and_is_bounded():
    assert extract_questions("") == [] and extract_questions(None) == [] and extract_questions("no list here") == []
    assert extract_questions("questions:   |  | ") == []
    many = "QUESTIONS: " + " | ".join(f"Question number {i}" for i in range(80))
    assert len(extract_questions(many)) == 25 and len(extract_questions("QUESTIONS: " + "q" * 400)[0]) == 140
    assert extract_questions("  QUESTIONS:   Spaced   out    question  ") == ["Spaced out question"]


def _rows():
    return [
        {"url": "https://boards.greenhouse.io/a/jobs/1", "questions": ["Are you legally authorized to work in the UK?", "Notice period", "Notice period"]},
        {"url": "https://jobs.lever.co/b/2", "questions": ["Are you legally authorized to work in the UK? *", "Salary expectations (required)"]},
        {"url": "https://jobs.ashbyhq.com/c/3", "site": "Ashby", "questions": ["are you legally authorized to work in the uk", "Notice period:"]},
        {"url": "https://x.example/4"}, {"url": "https://x.example/5", "questions": None}, {"url": "https://x.example/6", "questions": ["ab"]},
    ]


def test_question_counts_group_spelling_variants_and_count_once_per_application():
    ranked = outcomes.question_counts(_rows())
    assert ranked[0] == {"question": "Are you legally authorized to work in the UK?", "count": 3, "sites": ["Ashby", "Greenhouse", "Lever"]}
    notice = next(r for r in ranked if r["question"].startswith("Notice period"))
    assert notice["count"] == 2                                          # the repeat inside one application did not count twice
    assert [r["question"] for r in ranked][-1] == "Salary expectations (required)" and len(ranked) == 3     # too-short text is ignored
    assert outcomes.question_counts(_rows(), top=1) == ranked[:1] and outcomes.question_counts([]) == [] and outcomes.question_counts(_rows(), top=-5) == []


def test_the_outcomes_command_lists_the_questions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    args = argparse.Namespace(json=False, recent=0, questions=True)
    outcomes_command.run(args)
    assert "No questions recorded yet" in capsys.readouterr().out
    for row in _rows():
        outcomes.append_outcome({**row, "status": "needs_review"})
    outcomes_command.run(args)
    out = capsys.readouterr().out
    assert "6 attempts" in out and "Are you legally authorized to work in the UK?" in out and "Ashby, Greenhouse, Lever" in out
    outcomes_command.run(argparse.Namespace(json=True, recent=0, questions=True))
    data = json.loads(capsys.readouterr().out)
    assert data["attempts"] == 6 and data["questions"][0]["count"] == 3
    outcomes_command.run(argparse.Namespace(json=False, recent=0, questions=False))
    assert "attempts recorded" in capsys.readouterr().out


def test_the_questions_flag_is_a_real_command_line_option():
    from job_finder.cli_parser import build_parser
    parsed = build_parser("0.0").parse_args(["outcomes", "--questions", "--json"])
    assert parsed.questions is True and parsed.json is True
