"""A small fake job board for testing the browser agent without touching a real company.

It serves one job page per applicant tracking system in the shape the agent meets in the wild (Greenhouse: split names
and a select; Lever: one full-name field; Ashby: the real file input hidden behind an "Upload" button and a radio group).
Each form posts to this server, which checks the required fields and keeps what it received, so a test can say exactly
which fields the agent filled. Submitting here is safe: nothing leaves your computer.

    python tests/bench/board.py            # serves on http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import threading
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

PAGE = "<!doctype html><html><head><meta charset='utf-8'><title>{title}</title></head><body>{body}</body></html>"

FORMS: Dict[str, Dict[str, Any]] = {
    "greenhouse": {
        "title": "AI Engineer at Bench Co (Greenhouse)",
        "required": ["first_name", "last_name", "email", "phone", "resume", "work_authorization"],
        "fields": """
          <label for='first_name'>First Name *</label><input id='first_name' name='first_name' required>
          <label for='last_name'>Last Name *</label><input id='last_name' name='last_name' required>
          <label for='email'>Email *</label><input id='email' name='email' type='email' required>
          <label for='phone'>Phone *</label><input id='phone' name='phone' required>
          <label for='resume'>Resume/CV *</label><input id='resume' name='resume' type='file'>
          <label for='linkedin'>LinkedIn Profile</label><input id='linkedin' name='linkedin'>
          <label for='work_authorization'>Are you legally authorized to work in the United Kingdom? *</label>
          <select id='work_authorization' name='work_authorization'><option value=''>Select...</option><option>Yes</option><option>No</option></select>
        """,
    },
    "lever": {
        "title": "Machine Learning Engineer at Bench Co (Lever)",
        "required": ["name", "email", "phone", "resume", "current_company"],
        "fields": """
          <label for='name'>Full name *</label><input id='name' name='name' required>
          <label for='email'>Email *</label><input id='email' name='email' type='email' required>
          <label for='phone'>Phone *</label><input id='phone' name='phone' required>
          <label for='current_company'>Current company *</label><input id='current_company' name='current_company' required>
          <label for='resume'>Resume/CV *</label><input id='resume' name='resume' type='file'>
          <label for='github'>GitHub URL</label><input id='github' name='github'>
        """,
    },
    "ashby": {
        "title": "Applied AI Engineer at Bench Co (Ashby)",
        "required": ["name", "email", "resume", "right_to_work"],
        "fields": """
          <label for='name'>Name *</label><input id='name' name='name' required>
          <label for='email'>Email *</label><input id='email' name='email' type='email' required>
          <label>Resume *</label>
          <button type='button' onclick="document.getElementById('resume').click()">Upload File</button>
          <input id='resume' name='resume' type='file' style='display:none'>
          <fieldset><legend>Do you have the right to work in the UK? *</legend>
            <label><input type='radio' name='right_to_work' value='Yes'> Yes</label>
            <label><input type='radio' name='right_to_work' value='No'> No</label></fieldset>
        """,
    },
}


def job_page(ats: str) -> str:
    form = FORMS[ats]
    body = (f"<h1>{form['title']}</h1><p>Join Bench Co to build AI products in London.</p>"
            f"<form method='post' action='/{ats}/apply' enctype='multipart/form-data'>{form['fields']}"
            "<button type='submit'>Submit application</button></form>")
    return PAGE.format(title=form["title"], body=body)


def index_page() -> str:
    links = "".join(f"<li><a href='/{ats}/job'>{f['title']}</a></li>" for ats, f in FORMS.items())
    return PAGE.format(title="Bench jobs", body=f"<h1>Open roles</h1><ul>{links}</ul>")


def parse_multipart(content_type: str, body: bytes) -> Dict[str, Any]:
    """Field values from a multipart/form-data body. A file field maps to its file name (empty when none was chosen)."""
    message = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    out: Dict[str, Any] = {}
    for part in message.iter_parts() if message.is_multipart() else []:
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        out[name] = (filename or "") if filename is not None else (part.get_content() if part.get_content_type().startswith("text") else "").strip()
    return out


class Board:
    """The server plus everything it received. Use as a context manager in tests."""

    def __init__(self, port: int = 0) -> None:
        self.submissions: List[Tuple[str, Dict[str, Any]]] = []
        board = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

            def _send(self, status: int, html: str) -> None:
                data = html.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                path = urlparse(self.path).path.strip("/")
                if path == "":
                    return self._send(200, index_page())
                ats, _, rest = path.partition("/")
                if ats in FORMS and rest == "job":
                    return self._send(200, job_page(ats))
                if path == "submissions":
                    return self._send(200, json.dumps(board.submissions))
                self._send(404, PAGE.format(title="Not found", body="<h1>Not found</h1>"))

            def do_POST(self) -> None:
                ats, _, rest = urlparse(self.path).path.strip("/").partition("/")
                if ats not in FORMS or rest != "apply":
                    return self._send(404, PAGE.format(title="Not found", body="<h1>Not found</h1>"))
                length = int(self.headers.get("Content-Length") or 0)
                values = parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
                missing = [f for f in FORMS[ats]["required"] if not str(values.get(f, "")).strip()]
                if missing:
                    return self._send(400, PAGE.format(title="Missing fields", body="<h1>Please fix the form</h1><p>Missing: " + ", ".join(missing) + "</p>"))
                board.submissions.append((ats, values))
                self._send(200, PAGE.format(title="Thanks", body="<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>"))

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "Board":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":
    with Board(8765) as board:
        print("Bench board on", board.base, "(Ctrl+C to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
