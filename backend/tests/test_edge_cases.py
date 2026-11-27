"""Small branches in several modules: bad input, odd mail, and the cleanup that only runs after something else went wrong."""
import os
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
import account_login as al  # noqa: E402
from applications_tracker import replies  # noqa: E402
from services import account_data, app_login  # noqa: E402
from services.relevance import _as_list, check_relevance, location_check, sponsorship_check  # noqa: E402


# ── mail ─────────────────────────────────────────────────────────────────────────
def test_header_decoding_handles_encoded_words_bytes_and_nothing():
    assert replies.decode(None) == "" and replies.decode("") == ""
    assert replies.decode("=?utf-8?q?Interview_with_Z=C3=BCrich?=") == "Interview with Zürich"
    assert replies.decode("Plain subject") == "Plain subject"


def test_plain_text_is_taken_from_the_first_text_part_and_bounded():
    simple = EmailMessage()
    simple.set_content("Hello there")
    assert replies.plain_text(simple).strip() == "Hello there"
    multi = EmailMessage()
    multi.set_content("fallback text")
    multi.add_alternative("<p>html version</p>", subtype="html")
    assert "fallback" in replies.plain_text(multi)
    html_only = EmailMessage()
    html_only.set_content("<p>only html</p>", subtype="html")
    assert replies.plain_text(html_only) == ""
    long = EmailMessage()
    long.set_content("x" * 9000)
    assert len(replies.plain_text(long, limit=100)) == 100


def test_applications_without_a_company_or_link_are_skipped_and_logout_errors_ignored(monkeypatch):
    apps = [{"company": "", "url": "https://x.example/1", "status": "Applied"}, {"company": "Acme", "url": "", "status": "Applied"}]
    assert replies.find_updates(apps, [{"from": "a@acme.com", "subject": "Interview", "body": "schedule a call"}]) == []

    class Imap:
        def __init__(self, host, timeout=None): pass
        def login(self, u, p): pass
        def select(self, box, readonly=False): pass
        def search(self, *a): return "OK", [b""]
        def logout(self): raise OSError("connection already closed")

    monkeypatch.setattr(replies.imaplib, "IMAP4_SSL", Imap)
    assert replies.fetch_messages("imap.example.com", "me@example.com", "pw") == []        # an empty inbox, and the failed logout is ignored


# ── the loopback sign-in ─────────────────────────────────────────────────────────
def test_close_can_be_called_twice_and_the_listener_frees_its_port():
    r = al.LoopbackReceiver("s").start()
    port = r.port
    r.close()
    r.close()
    import socket
    probe = socket.socket()
    probe.bind(("127.0.0.1", port))                                                          # the port is free again
    probe.close()


def test_a_reply_without_a_token_is_treated_as_a_failed_sign_in():
    import threading
    state = {}

    def post(path, body):
        if path == "/auth/app/begin":
            state["begin"] = body
            return {"login_url": "https://www.job-finder.space/auth/url"}
        return {"email": "me@example.com"}                                                     # no token in the answer

    def browser(url):
        import urllib.request
        threading.Thread(target=lambda: urllib.request.urlopen(f"http://127.0.0.1:{state['begin']['port']}/callback?code=c&state={state['begin']['state']}", timeout=5).read(), daemon=True).start()

    with pytest.raises(RuntimeError, match="did not accept"):
        al.run_google_sign_in(post, browser, timeout=10)


# ── sign-in codes and the relevance rules ────────────────────────────────────────
def test_exchange_ignores_requests_that_are_not_even_shaped_like_a_secret():
    assert app_login.exchange(None, "v" * 43) is None and app_login.exchange("code", None) is None and app_login.exchange("code", "short") is None
    assert app_login.exchange("code", "v" * 43) is None                                      # a well-formed secret but an unknown code


def test_relevance_reads_lists_in_every_shape():
    assert _as_list("London, Remote; Leeds\nYork") == ["London", "Remote", "Leeds", "York"]
    assert _as_list(("a", " b ", "")) == ["a", "b"] and _as_list(None) == [] and _as_list(5) == []


def test_location_accepts_a_matching_country_name_and_rejects_a_far_place():
    assert location_check("Greater Manchester, United Kingdom", {"target_locations": ["Leeds, UK"]}) == (True, "")      # same country, different city
    assert location_check("Berlin, Germany", {"target_locations": ["Leeds, UK"]})[0] is False
    assert location_check("Anywhere", {"target_locations": ["Remote"]})[0] is False                                      # "remote" must actually be in the job's place
    assert location_check("Remote (EU)", {"target_locations": ["Remote"]}) == (True, "")


def test_sponsorship_wording_variants_and_blank_profiles():
    needs = {"requires_sponsorship": True}
    for text in ("We cannot sponsor visas.", "No visa sponsorship available.", "Candidates must have the right to work in the UK.",
                 "Applicants must be authorised to work in the US.", "We do not offer sponsorship."):
        assert sponsorship_check(text, needs)[0] is False, text
    assert sponsorship_check("We love sponsors of the arts.", needs)[0] is True
    assert sponsorship_check("", needs)[0] is True and sponsorship_check(None, needs)[0] is True
    assert check_relevance({}, "", {}, {}) == (True, "")


# ── deleting an account ──────────────────────────────────────────────────────────
def test_delete_also_removes_the_local_folder_of_the_token_and_never_one_outside_the_output_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(account_data, "get_output_dir", lambda: str(tmp_path))
    mine = tmp_path / "ABC123"
    mine.mkdir()
    (mine / "resume.json").write_text("{}")
    sibling = tmp_path / "OTHER99"
    sibling.mkdir()
    monkeypatch.setattr(account_data, "supabase_request", lambda path, method="GET", data=None: [])
    out = account_data.delete_user_data({"id": 7}, token="ABC123")
    assert out["deleted"] is True and not mine.exists() and sibling.exists()
    assert account_data._local_dir("../../etc") is None or str(account_data._local_dir("../../etc")).startswith(str(tmp_path))
    assert account_data._local_dir(None) is None or str(account_data._local_dir(None)).startswith(str(tmp_path))
