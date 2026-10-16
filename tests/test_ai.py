import json

import pytest

from rameau import ai


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "RAMEAU_AI_MODEL",
                "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    kr = FakeKeyring()
    monkeypatch.setattr(ai, "_keyring", lambda: kr)
    monkeypatch.setattr(ai, "_settings_path", lambda: tmp_path / "settings.json")
    return kr, tmp_path


def test_no_key_means_ai_off(env):
    assert ai.list_profiles() == [] and ai.active_profile() is None
    with pytest.raises(ai.AIUnavailable):
        ai.ask_tutor("Why V7?", "context")


def test_add_switch_and_remove_named_keys(env):
    kr, tmp = env
    ai.add_profile("Personal", "sk-ant-personal")
    ai.add_profile("Work", "sk-ant-work")
    assert ai.list_profiles() == ["Personal", "Work"]
    assert ai.active_profile() == "Work"
    ai.set_active_profile("Personal")
    assert ai.active_profile() == "Personal"
    assert ai.profile_key("Work") == "sk-ant-work"
    ai.remove_profile("Personal")
    assert ai.list_profiles() == ["Work"] and ai.active_profile() == "Work"
    assert ai.profile_key("Personal") is None


def test_keys_never_reach_the_settings_file(env):
    kr, tmp = env
    ai.add_profile("Personal", "sk-ant-secret-value")
    ai.set_model("claude-sonnet-5-5")
    text = (tmp / "settings.json").read_text(encoding="utf-8")
    assert "sk-ant" not in text
    assert json.loads(text)["ai_models"]["Personal"] == "claude-sonnet-5-5"


def test_environment_key_is_its_own_profile(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    ai.add_profile("Personal", "sk-ant-personal", activate=False)
    assert ai.list_profiles() == [ai.ENV_ANTHROPIC, "Personal"]
    assert ai.active_profile() == ai.ENV_ANTHROPIC
    with pytest.raises(ValueError):
        ai.remove_profile(ai.ENV_ANTHROPIC)


def test_legacy_single_key_is_migrated(env):
    kr, tmp = env
    kr.set_password(ai.KEYCHAIN_SERVICE, ai.LEGACY_KEYCHAIN_USER, "sk-ant-old")
    assert ai.list_profiles() == ["Default"]
    assert ai.profile_key("Default") == "sk-ant-old"
    assert kr.get_password(ai.KEYCHAIN_SERVICE, ai.LEGACY_KEYCHAIN_USER) is None


def test_client_uses_the_active_profiles_key(env):
    ai.add_profile("Work", "sk-ant-work")
    assert ai._client().api_key == "sk-ant-work"


def test_default_model_is_haiku(env):
    assert ai.model_name() == "claude-haiku-5-5"


def test_extract_abc_from_reply():
    reply = "```abc\nX:1\nT:Test\nM:4/4\nL:1/4\nK:C\nC D E F | HG4 |]\n```\nA rising tune."
    abc = ai._extract_abc(reply)
    assert abc.startswith("X:1") and "K:C" in abc
    assert ai._extract_abc("no music here") is None


def test_openai_keys_and_per_key_models(env, monkeypatch):
    kr, tmp = env
    ai.add_profile("Claude", "sk-ant-claude")
    ai.add_profile("GPT", "sk-openai-gpt", provider=ai.OPENAI)
    assert ai.provider_of("GPT") == ai.OPENAI and ai.provider_of("Claude") == ai.ANTHROPIC
    ai.set_model("gpt-5.4-mini", "GPT")
    ai.set_model("claude-sonnet-5-5", "Claude")
    assert ai.model_name("GPT") == "gpt-5.4-mini" and ai.model_name("Claude") == "claude-sonnet-5-5"
    assert ai._client("GPT").api_key == "sk-openai-gpt"
    assert ai._client("Claude").api_key == "sk-ant-claude"
    assert "sk-openai" not in (tmp / "settings.json").read_text()


def test_openai_compatible_server_address(env):
    ai.add_profile("Local", "", provider=ai.OPENAI, base_url="http://localhost:11434/v1")
    client = ai._client("Local")
    assert str(client.base_url).startswith("http://localhost:11434/v1")


def test_openai_environment_key_appears(env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert ai.ENV_OPENAI in ai.list_profiles()
    assert ai.provider_of(ai.ENV_OPENAI) == ai.OPENAI


def test_openai_model_filter_prefers_mini_chat_models():
    from rameau import ai_openai

    class Fake:
        class models:
            @staticmethod
            def list():
                return [type("M", (), {"id": i}) for i in (
                    "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-mini-2026-03-17", "text-embedding-3-large",
                    "whisper-1", "gpt-realtime-2.1-mini", "tts-1", "o4-mini")]

    ids = [m for m, _ in ai_openai.list_models(Fake)]
    assert "text-embedding-3-large" not in ids and "whisper-1" not in ids and "gpt-realtime-2.1-mini" not in ids
    assert ids[0].endswith("mini") or "mini" in ids[0]
    assert ai_openai.default_model(Fake) in ("gpt-5.4-mini", "o4-mini")
