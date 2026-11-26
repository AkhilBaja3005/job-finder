import inspect
import types

import pytest

from services import browser_use_agent as agent
from services import browser_use_helpers as helpers
from services import gemini_client as g


# ── defaults ────────────────────────────────────────────────────────────────────
def test_agent_defaults_to_sonnet_and_text_defaults_to_haiku():
    from config.constants import DEFAULT_MODEL_FAMILY
    assert agent._DEFAULT_FAMILY["anthropic"] == "sonnet"
    assert DEFAULT_MODEL_FAMILY["anthropic"] == "haiku"


def test_tab_cap_and_run_timeout_defaults(monkeypatch):
    monkeypatch.delenv("BROWSER_USE_TIMEOUT", raising=False)
    assert helpers.get_run_timeout() == 600.0
    monkeypatch.setenv("BROWSER_USE_TIMEOUT", "120")
    assert helpers.get_run_timeout() == 120.0
    assert 'JOB_FINDER_MAX_TABS", "6"' in inspect.getsource(agent.rotate_chrome_instance)


def test_prompt_tells_the_agent_how_to_recover_from_the_upload_error(monkeypatch):
    monkeypatch.setenv("PORTALS_PASSWORD", "x")
    text = agent.build_application_task_prompt(
        "https://example.com/job", {"name": "A", "email": "a@b.c", "phone": "+447000000000", "location": "London, UK"}, "/tmp/r.pdf", True)
    assert "Node is not a file input element" in text and 'input type="file"' in text


# ── Gemini overload retry ───────────────────────────────────────────────────────
class _Models:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return types.SimpleNamespace(text=outcome)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(g, "_sleep", recorded.append)
    monkeypatch.setattr(g, "_throttle_for_rpm", lambda model: None)
    monkeypatch.setattr(g, "get_gemini_api_keys", lambda: ["AIza-test-key"])
    return recorded


def _run(monkeypatch, outcomes):
    models = _Models(outcomes)
    monkeypatch.setattr(g, "get_gemini_client", lambda key: types.SimpleNamespace(models=models))
    return models


def test_a_busy_model_is_retried_before_moving_on(sleeps, monkeypatch):
    models = _run(monkeypatch, [RuntimeError("503 UNAVAILABLE high demand"), "answer"])
    assert g._generate_with_gemini("hi", ["model-a", "model-b"]) == "answer"
    assert models.calls == 2 and sleeps == [1.5]  # same model, one short wait


def test_retries_are_limited_then_the_next_model_is_tried(sleeps, monkeypatch):
    busy = RuntimeError("503 UNAVAILABLE")
    models = _run(monkeypatch, [busy, busy, busy, "from-b"])
    assert g._generate_with_gemini("hi", ["model-a", "model-b"]) == "from-b"
    assert models.calls == 4 and sleeps == [1.5, 3.0]  # three tries on model-a, then model-b


def test_other_errors_do_not_wait(sleeps, monkeypatch):
    models = _run(monkeypatch, [RuntimeError("400 invalid argument"), "from-b"])
    assert g._generate_with_gemini("hi", ["model-a", "model-b"]) == "from-b"
    assert models.calls == 2 and sleeps == []


def test_rate_limits_still_rotate_without_waiting(sleeps, monkeypatch):
    models = _run(monkeypatch, [RuntimeError("429 RESOURCE_EXHAUSTED"), "from-b"])
    assert g._generate_with_gemini("hi", ["model-a", "model-b"]) == "from-b"
    assert sleeps == [] and models.calls == 2


def test_prompt_carries_work_history_education_and_skills():
    from services.browser_use_agent import build_application_task_prompt
    prompt = build_application_task_prompt("https://x.example/job", {
        "name": "Ada", "email": "ada@example.com",
        "work_experience": [{"title": "Engineer", "company": "Acme Ltd", "start": "2022"}, {"title": "Intern", "company": "Old Co"}],
        "education": [{"degree": "BSc Computer Science", "school": "UCL", "end": "2021"}],
        "core_skills": ["Python", "SQL"],
    })
    assert "CURRENT employer" in prompt and "Engineer | Acme Ltd | 2022" in prompt
    assert "BSc Computer Science | UCL | 2021" in prompt and "Skills: Python, SQL" in prompt


def test_prompt_works_without_background_and_has_no_hardcoded_personal_defaults():
    from services.browser_use_agent import build_application_task_prompt
    prompt = build_application_task_prompt("https://x.example/job", {"name": "Ada"})
    assert "Work history" not in prompt
    assert "W12 0BZ" not in prompt and "akhilbaja3005.github.io" not in prompt
