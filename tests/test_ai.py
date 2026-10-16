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
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "RAMEAU_AI_MODEL"):
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
    text = (tmp / "settings.json").read_text()
    assert "sk-ant" not in text
    assert json.loads(text)["ai_model"] == "claude-sonnet-5-5"


def test_environment_key_is_its_own_profile(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    ai.add_profile("Personal", "sk-ant-personal", activate=False)
    assert ai.list_profiles() == [ai.ENV_PROFILE, "Personal"]
    assert ai.active_profile() == ai.ENV_PROFILE
    with pytest.raises(ValueError):
        ai.remove_profile(ai.ENV_PROFILE)


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
