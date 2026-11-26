import pytest
from services import browser_use_agent as b

ENVS = ("BROWSER_USE_PROVIDERS", "BROWSER_USE_MODEL", "BROWSER_USE_ANTHROPIC_MODEL",
        "BROWSER_USE_OPENAI_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENVS:
        monkeypatch.delenv(k, raising=False)


def test_default_is_gemini_only_without_keys():
    assert b.resolve_provider_order() == ["gemini"]


def test_default_order_with_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    assert b.resolve_provider_order() == ["gemini", "anthropic", "openai"]


def test_explicit_provider_list_wins(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("BROWSER_USE_PROVIDERS", "openai, claude")
    assert b.resolve_provider_order() == ["openai", "anthropic", "gemini"]


def test_model_name_picks_primary(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    assert b.resolve_provider_order("gpt-4o")[0] == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert b.resolve_provider_order("claude-haiku-5-5")[0] == "anthropic"


def test_explicit_provider_model_env_makes_it_primary(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("BROWSER_USE_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert b.resolve_provider_order()[0] == "anthropic"


def test_provider_without_key_is_dropped(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_PROVIDERS", "anthropic,openai")
    assert b.resolve_provider_order() == ["gemini"]


def test_unknown_names_ignored(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_PROVIDERS", "bogus")
    assert b.resolve_provider_order() == ["gemini"]


def test_model_aliases(monkeypatch):
    assert b._expand_model_alias("anthropic", "haiku") == "claude-haiku-5-5"
    assert b._expand_model_alias("openai", "Luna") == "gpt-6-luna"
    assert b._expand_model_alias("openai", "terra") == "gpt-6.1-terra"
    assert b._expand_model_alias("openai", "gpt-4o") == "gpt-4o"
    assert b._provider_from_model("haiku") == "anthropic"
    assert b._provider_from_model("terra") == "openai"


def test_default_openai_model_is_luna():
    assert b._DEFAULT_MODELS["openai"] == "gpt-6-luna"
    assert b._DEFAULT_MODELS["anthropic"] == "claude-haiku-5-5"


from config.constants import pick_newest_model

OPENAI_IDS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-6-luna", "gpt-6-sol", "gpt-6.1-terra", "gpt-6.1-sol",
              "gpt-6-astra", "gpt-6.2-astra", "gpt-6.1-sol-healthcare", "gpt-5.5"]
ANTHROPIC_IDS = ["claude-haiku-4-5-20251001", "claude-haiku-5-5", "claude-haiku-5-5-20260301",
                 "claude-sonnet-5-5", "claude-opus-4-1-20250805"]


def test_pick_newest_openai():
    assert pick_newest_model("openai", "luna", OPENAI_IDS) == "gpt-6-luna"
    assert pick_newest_model("openai", "terra", OPENAI_IDS) == "gpt-6.1-terra"
    assert pick_newest_model("openai", "luna", ["gpt-6-sol"]) is None


def test_pick_newest_anthropic():
    assert pick_newest_model("anthropic", "haiku", ANTHROPIC_IDS) == "claude-haiku-5-5"
    assert pick_newest_model("anthropic", "opus", ANTHROPIC_IDS) == "claude-opus-4-1-20250805"


def test_alias_uses_discovery_and_explicit_names_are_untouched(monkeypatch):
    import config.constants as c
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(c, "_list_provider_model_ids", lambda provider, key: OPENAI_IDS + ["gpt-7-luna"])
    c._PROVIDER_MODEL_CACHE.clear()
    assert b._expand_model_alias("openai", "luna") == "gpt-7-luna"
    assert b._expand_model_alias("openai", "gpt-6-luna") == "gpt-6-luna"
    c._PROVIDER_MODEL_CACHE.clear()


def test_discovery_failure_falls_back_to_static(monkeypatch):
    import config.constants as c
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    def boom(provider, key):
        raise OSError("offline")
    monkeypatch.setattr(c, "_list_provider_model_ids", boom)
    c._PROVIDER_MODEL_CACHE.clear()
    assert b._expand_model_alias("openai", "terra") == "gpt-6.1-terra"
    c._PROVIDER_MODEL_CACHE.clear()
