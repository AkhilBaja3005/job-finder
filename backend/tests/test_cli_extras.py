import csv
import json
import os

from job_finder import ats_view, commands_extra

GOLDEN = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "ats_golden.json"), encoding="utf-8"))


def test_mask_secrets_nested():
    data = {"candidate": {"name": "J", "portals_password": "hunter2", "api_key": "k", "profiles": [{"github_token": "t", "url": "u"}]}}
    masked = commands_extra.mask_secrets(data)
    assert masked["candidate"]["portals_password"] == "********"
    assert masked["candidate"]["api_key"] == "********"
    assert masked["candidate"]["profiles"][0]["github_token"] == "********"
    assert masked["candidate"]["name"] == "J" and masked["candidate"]["profiles"][0]["url"] == "u"
    assert "hunter2" not in json.dumps(masked)


def test_export_csv_and_json_with_filter(tmp_path):
    apps = [
        {"company": "A", "job_title": "X", "score": 90, "status": "applied", "job_url": "u1"},
        {"company": "B", "job_title": "Y", "score": 70, "status": "failed", "job_url": "u2"},
    ]
    out_csv = tmp_path / "a.csv"
    commands_extra.export_applications(apps, str(out_csv), fmt="csv", status="applied")
    rows = list(csv.DictReader(open(out_csv, encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["company"] == "A"
    out_json = tmp_path / "a.json"
    commands_extra.export_applications(apps, str(out_json), fmt="json", status="all")
    assert len(json.load(open(out_json, encoding="utf-8"))) == 2


def test_score_against_jd_has_breakdown():
    jd = GOLDEN["cases"][0]["jd"]
    result = ats_view.score_against_jd(GOLDEN["resume"], jd, keyword=True)   # the offline engine: no LLM call in a unit test
    assert result["eligible"] and 0 <= result["overall"] <= 100
    assert "python" in result["matched_skills"]
    assert set(result) >= {"skills", "experience", "role_fit", "missing_skills", "breakdown"}


def test_ats_render_json_and_ineligible(capsys):
    assert ats_view.render({"eligible": False, "reason": "visa", "overall": 0}, as_json=True) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "visa"


def test_cover_letter_command_uses_generator(monkeypatch, tmp_path, capsys):
    import backend.job_finder_mcp.tools.profile_tools as pt
    import backend.services.cover_letter_generator as gen
    monkeypatch.setattr(pt, "load_profile_data", lambda: {"candidate": {"name": "Jane"}})
    monkeypatch.setattr(gen, "generate_structured_cover_letter",
                        lambda **kw: {"status": "needs_review", "cover_letter": "Dear Team", "warnings": ["Too short"]})
    out = tmp_path / "l.txt"
    code = commands_extra.run_cover_letter("Eng", "Acme", None, None, str(out))
    assert code == 0 and out.read_text(encoding="utf-8").strip() == "Dear Team"
    assert "Too short" in capsys.readouterr().err


def test_cover_letter_fallback_exit_code(monkeypatch):
    import backend.job_finder_mcp.tools.profile_tools as pt
    import backend.services.cover_letter_generator as gen
    monkeypatch.setattr(pt, "load_profile_data", lambda: {"candidate": {"name": "Jane"}})
    monkeypatch.setattr(gen, "generate_structured_cover_letter",
                        lambda **kw: {"status": "fallback", "cover_letter": "x", "warnings": ["down"]})
    assert commands_extra.run_cover_letter("Eng", "Acme", None, None, None) == 2
