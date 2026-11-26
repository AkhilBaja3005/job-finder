import json

from services import saved_answers
from services.browser_use_agent import build_application_task_prompt  # noqa: F401  (import must keep working)


def test_template_is_created_once_and_never_overwritten(tmp_path):
    path = saved_answers.ensure_template(str(tmp_path))
    first = open(path).read()
    open(path, "w").write(json.dumps([{"question": "Q", "answer": "A"}]))
    saved_answers.ensure_template(str(tmp_path))
    assert json.loads(open(path).read()) == [{"question": "Q", "answer": "A"}]
    assert json.loads(first)[0]["question"].startswith("Why do you want")


def test_load_skips_bad_entries_and_caps_length(tmp_path):
    (tmp_path / "saved_answers.json").write_text(json.dumps([
        {"question": "Notice period", "answer": "x" * 2000}, {"question": "", "answer": "no"}, "text", {"question": "No answer", "answer": " "},
    ]))
    got = saved_answers.load_saved_answers(str(tmp_path))
    assert len(got) == 1 and len(got[0]["answer"]) == saved_answers.MAX_CHARS
    assert saved_answers.load_saved_answers(str(tmp_path / "missing")) == []
    (tmp_path / "saved_answers.json").write_text("{broken")
    assert saved_answers.load_saved_answers(str(tmp_path)) == []


def test_prompt_block_is_empty_without_answers_and_lists_them_with():
    assert saved_answers.prompt_block("/nonexistent/folder") == ""


def test_prompt_block_contents(tmp_path):
    (tmp_path / "saved_answers.json").write_text(json.dumps([{"question": "Start date", "answer": "1 March"}]))
    block = saved_answers.prompt_block(str(tmp_path))
    assert "Question: Start date" in block and "Answer: 1 March" in block and "exactly as written" in block


def test_form_save_drops_blank_rows_caps_text_and_replaces_the_file(tmp_path):
    saved = saved_answers.save_saved_answers(str(tmp_path), [
        {"question": " Why us? ", "answer": " Because. "}, {"question": "", "answer": "orphan"}, {"question": "No answer", "answer": " "},
        "junk", {"question": "q" * 500, "answer": "a" * 2000},
    ])
    assert saved == {"saved": 2}
    got = saved_answers.load_saved_answers(str(tmp_path))
    assert got[0] == {"question": "Why us?", "answer": "Because."}
    assert len(got[1]["question"]) == 200 and len(got[1]["answer"]) == saved_answers.MAX_CHARS
    assert not list(tmp_path.glob("*.tmp"))
    assert saved_answers.save_saved_answers(str(tmp_path), "not a list") == {"saved": 0}
    assert saved_answers.load_saved_answers(str(tmp_path)) == []


def test_form_save_keeps_at_most_forty_answers(tmp_path):
    many = [{"question": f"Q{i}", "answer": "A"} for i in range(60)]
    assert saved_answers.save_saved_answers(str(tmp_path), many) == {"saved": saved_answers.MAX_ENTRIES}
