import pytest
from services import gemini_client as g

ENVS = ("LLM_PROVIDERS", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_OPENAI_MODEL", "LLM_ANTHROPIC_MODEL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(g, "get_gemini_api_keys", lambda: ["AIza-test"])


def test_default_order(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    assert g._text_provider_order() == ["gemini", "anthropic", "openai"]


def test_custom_order_and_aliases(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_PROVIDERS", "openai, claude")
    assert g._text_provider_order() == ["openai", "anthropic", "gemini"]


def test_providers_without_keys_are_dropped():
    assert g._text_provider_order() == ["gemini"]


def test_no_keys_at_all(monkeypatch):
    monkeypatch.setattr(g, "get_gemini_api_keys", lambda: [])
    assert g._text_provider_order() == []


def _stub_stages(monkeypatch):
    monkeypatch.setattr(g, "_nvidia_configured", lambda: False)
    monkeypatch.setattr(g, "_cloudflare_configured", lambda: False)


def test_falls_through_to_next_provider(monkeypatch):
    _stub_stages(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    calls = []

    def gem(*a, **k):
        calls.append("gemini")
        raise RuntimeError("503")

    def ant(*a, **k):
        calls.append("anthropic")
        raise RuntimeError("overloaded")

    def oai(*a, **k):
        calls.append("openai")
        return "from-openai"

    monkeypatch.setattr(g, "_generate_with_gemini", gem)
    monkeypatch.setattr(g, "_execute_anthropic", ant)
    monkeypatch.setattr(g, "_execute_openai", oai)
    assert g._generate_with_model_list("hi", ["m"]) == "from-openai"
    assert calls == ["gemini", "anthropic", "openai"]


def test_primary_provider_is_used_first(monkeypatch):
    _stub_stages(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("LLM_PROVIDERS", "anthropic,gemini")
    monkeypatch.setattr(g, "_execute_anthropic", lambda *a, **k: "from-claude")
    monkeypatch.setattr(g, "_generate_with_gemini", lambda *a, **k: pytest.fail("gemini must not run"))
    assert g._generate_with_model_list("hi", ["m"]) == "from-claude"


def test_all_fail_raises(monkeypatch):
    _stub_stages(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(g, "_generate_with_gemini", boom)
    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        g._generate_with_model_list("hi", ["m"])


def test_user_supplied_keys_pick_their_own_provider(monkeypatch):
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(g, "_execute_anthropic", lambda prompt, schema, key, *a, **k: seen.setdefault("anthropic", key) or "claude")
    monkeypatch.setattr(g, "_execute_openai", lambda prompt, schema, key, *a, **k: seen.setdefault("openai", key) or "gpt")
    monkeypatch.setattr(g, "_generate_with_gemini", lambda *a, **k: pytest.fail("server Gemini must not run"))
    assert g._generate_with_model_list("hi", ["m"], custom_api_key="sk-ant-user-key") == "sk-ant-user-key"
    assert g._generate_with_model_list("hi", ["m"], custom_api_key="sk-proj-user-key") == "sk-proj-user-key"
    assert seen == {"anthropic": "sk-ant-user-key", "openai": "sk-proj-user-key"}


def test_model_list_cache_is_per_key(monkeypatch):
    import config.constants as c
    calls = []

    def fake_list(provider, key):
        calls.append(key)
        return ["gpt-6-luna"] if key == "key-a" else ["gpt-7-luna"]

    monkeypatch.setattr(c, "_list_provider_model_ids", fake_list)
    c._PROVIDER_MODEL_CACHE.clear()
    assert c.discover_provider_model("openai", "luna", "key-a", "x") == "gpt-6-luna"
    assert c.discover_provider_model("openai", "luna", "key-b", "x") == "gpt-7-luna"
    assert c.discover_provider_model("openai", "luna", "key-a", "x") == "gpt-6-luna"
    assert calls == ["key-a", "key-b"]
    assert all("key-" not in k for k in c._PROVIDER_MODEL_CACHE)
    c._PROVIDER_MODEL_CACHE.clear()
