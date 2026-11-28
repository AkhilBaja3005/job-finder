"""Acceptance tests for Phase 7: Review experience (tasks 7.1 - 7.7)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MACAPP_DIR = str(Path(__file__).resolve().parents[2] / "macapp")
if _MACAPP_DIR not in sys.path:
    sys.path.insert(0, _MACAPP_DIR)

from scan_panel import (
    build_bulk_regen_summary,
    check_signoff_allowed,
    honest_cover_letter_message,
    honest_tailoring_message,
    revert_cv_change_in_json,
)


def test_at_7_1_revert_restores_original_bullet(tmp_path: Path):
    cv_path = tmp_path / "cv.json"
    cv_path.write_text(
        json.dumps(
            {
                "summary": "New summary",
                "experience": [
                    {"role": "ML Engineer", "company": "Acme", "description": ["Rewritten bullet text"]}
                ],
                "changes": [
                    {
                        "id": "chg_0",
                        "section": "experience",
                        "role_index": 0,
                        "bullet_index": 0,
                        "original": "Original bullet text",
                        "new_text": "Rewritten bullet text",
                        "reason": "Lead with Python",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ok, msg = revert_cv_change_in_json(cv_path, "chg_0")
    assert ok, msg
    updated = json.loads(cv_path.read_text(encoding="utf-8"))
    assert updated["experience"][0]["description"][0] == "Original bullet text"
    assert updated["edited_by_user"] is True
    assert updated["changes"][0]["reverted"] is True


def test_at_7_4_honest_cover_letter_and_tailoring_messages():
    states = ["not_asked", "skipped", "failed", "not_generated"]
    msgs = {honest_cover_letter_message(s) for s in states}
    assert len(msgs) == 4
    assert all("No cover letter required" not in m for m in msgs)

    t_msgs = {honest_tailoring_message(s) for s in ("not_tailored", "fallback_master", "failed", "not_generated")}
    assert len(t_msgs) == 4


def test_at_7_6_signoff_gate_blocks_unresolved_flags(tmp_path: Path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps({"unresolved_flags": ["fact_check:invented_tool", "bad_link:example.com"]}),
        encoding="utf-8",
    )
    allowed, reason = check_signoff_allowed(pack)
    assert not allowed
    assert "fact_check" in reason

    (pack / "manifest.json").write_text(json.dumps({"unresolved_flags": []}), encoding="utf-8")
    allowed2, _ = check_signoff_allowed(pack)
    assert allowed2


def test_at_7_7_bulk_regenerate_summary_table():
    before = {"0012": 72.0, "0016": 68.0, "0018": 80.0}
    after = {"0012": 79.0, "0016": 84.0, "0018": 77.0}
    rows = build_bulk_regen_summary(before, after)
    by_id = {r["id"]: r for r in rows}
    assert by_id["0016"]["status"] == "improved"
    assert by_id["0016"]["delta"] == 16.0
    assert by_id["0018"]["status"] == "worse"
    assert by_id["0018"]["delta"] == -3.0


def test_at_7_2_and_7_3_ui_has_diff_evidence_scores_and_no_bogus_cover_text():
    app_js = (Path(__file__).resolve().parents[2] / "macapp" / "panel" / "app.js").read_text(encoding="utf-8")
    assert "No cover letter required for this posting." not in app_js
    assert "Evidence &amp; Risk" in app_js or "Evidence & Risk" in app_js
    assert "revert-change" in app_js
    assert "Master score" in app_js or "master_score" in app_js
