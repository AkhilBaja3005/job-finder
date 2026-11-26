"""The fake job board that the agent is tested against: its forms must behave like the real ones."""
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "bench"))
from board import FORMS, Board  # noqa: E402


def _post(url, fields, files=None):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    for k, fname in (files or {}).items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\r\n')
    body = ("".join(parts) + f"--{boundary}--\r\n").encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_every_ats_page_loads_and_lists_its_fields():
    with Board() as board:
        index = urllib.request.urlopen(board.base + "/").read().decode()
        for ats, form in FORMS.items():
            assert f"/{ats}/job" in index
            page = urllib.request.urlopen(f"{board.base}/{ats}/job").read().decode()
            for field in form["required"]:
                assert f"name='{field}'" in page, (ats, field)


def test_ashby_hides_the_real_file_input_behind_a_button():
    with Board() as board:
        page = urllib.request.urlopen(board.base + "/ashby/job").read().decode()
        assert "Upload File</button>" in page and "type='file' style='display:none'" in page


def test_missing_required_fields_are_rejected_and_named():
    with Board() as board:
        status, html = _post(f"{board.base}/greenhouse/apply", {"first_name": "Ada", "email": "ada@example.com"})
        assert status == 400 and "last_name" in html and "resume" in html and "work_authorization" in html
        assert board.submissions == []


def test_complete_submission_is_accepted_and_recorded():
    with Board() as board:
        fields = {"name": "Ada Lovelace", "email": "ada@example.com", "right_to_work": "Yes"}
        status, html = _post(f"{board.base}/ashby/apply", fields, {"resume": "ada.pdf"})
        assert status == 200 and "Thank you for applying" in html
        ats, got = board.submissions[0]
        assert ats == "ashby" and got["name"] == "Ada Lovelace" and got["resume"] == "ada.pdf" and got["right_to_work"] == "Yes"


def test_a_form_submitted_without_a_file_fails_on_the_resume():
    with Board() as board:
        status, html = _post(f"{board.base}/lever/apply", {"name": "A", "email": "a@b.co", "phone": "1", "current_company": "X"})
        assert status == 400 and "resume" in html
