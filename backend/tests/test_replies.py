from applications_tracker import replies as r

APPS = [
    {"company": "Acme Ltd", "url": "https://jobs.example/acme/1", "status": "Applied (submitted)"},
    {"company": "Beta Labs", "url": "https://jobs.example/beta/2", "status": "Replied"},
    {"company": "Gamma", "url": "https://jobs.example/gamma/3", "status": "Applied"},
]


def msg(sender, subject, body=""):
    return {"from": sender, "subject": subject, "body": body}


def test_classify_separates_acknowledgements_rejections_and_interviews():
    assert r.classify("Thank you for applying to Acme", "We have received your application.") is None
    assert r.classify("Your application", "Unfortunately we will not be moving forward.") == "rejected"
    assert r.classify("Next steps", "We'd like to schedule a call to speak with you.") == "interview"
    assert r.classify("Offer", "We are pleased to offer you the role.") == "offer"
    assert r.classify("Quick question", "Do you have a portfolio link?") == "replied"


def test_company_matching_uses_name_domain_and_ignores_filler_words():
    assert r.mentions_company("Acme Ltd", "Recruiter <jo@acme.com>", "Hello", "")
    assert r.mentions_company("Acme Ltd", "jo@mail.example", "Your Acme application", "")
    assert not r.mentions_company("Acme Ltd", "jo@other.com", "Hello", "nothing relevant")
    assert not r.mentions_company("Ltd", "jo@ltd.com", "Hello", "")  # nothing left after filler words


def test_updates_move_forward_only_and_skip_automatic_mail():
    messages = [
        msg("jobs@acme.com", "Thank you for applying", "We have received your application"),
        msg("jo@acme.com", "Interview with Acme", "Could we schedule a call this week?"),
        msg("hr@beta.io", "Beta Labs update", "Unfortunately we are not moving forward."),   # rejected(2) vs current replied(1): later
        msg("noreply@gamma.com", "Thanks for your interest in Gamma", "Thank you for applying. We will review your application."),
    ]
    got = {u["company"]: u["stage"] for u in r.find_updates(APPS, messages)}
    assert got == {"Acme Ltd": "interview", "Beta Labs": "rejected"}


def test_an_application_already_further_along_is_not_downgraded():
    apps = [{"company": "Acme", "url": "https://x.example/1", "status": "Interview"}]
    assert r.find_updates(apps, [msg("a@acme.com", "Hello", "Quick question")]) == []


def test_fetch_reads_without_marking_read(monkeypatch):
    raw = b"From: Jo <jo@acme.com>\r\nSubject: Interview\r\nContent-Type: text/plain\r\n\r\nLet us schedule a call."
    calls = []

    class FakeIMAP:
        def __init__(self, host, timeout=None): calls.append(("connect", host))
        def login(self, u, p): calls.append(("login", u))
        def select(self, box, readonly=False): calls.append(("select", box, readonly))
        def search(self, *a): return "OK", [b"1 2"]
        def fetch(self, mid, spec): calls.append(("fetch", spec)); return "OK", [(b"1", raw), b")"]
        def logout(self): calls.append(("logout",))

    monkeypatch.setattr(r.imaplib, "IMAP4_SSL", FakeIMAP)
    out = r.fetch_messages("imap.example.com", "me@example.com", "app-password", days=7)
    assert len(out) == 2 and out[0]["subject"] == "Interview" and "schedule a call" in out[0]["body"]
    assert ("select", "INBOX", True) in calls and all("PEEK" in c[1] for c in calls if c[0] == "fetch") and calls[-1] == ("logout",)
