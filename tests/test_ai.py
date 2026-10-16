import json

import pytest

from rameau import ai


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ai, "keychain_key", lambda: None)
    monkeypatch.setattr(ai, "_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-profiles"))
    monkeypatch.setenv("HOME", str(tmp_path))


def test_key_source_is_none_without_key(no_key):
    assert ai.key_source() is None


def test_settings_never_store_secrets(no_key, tmp_path):
    ai.save_settings({"ai_model": "claude-haiku-5-5", "api_key": "sk-ant-should-not-be-saved"})
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved == {"ai_model": "claude-haiku-5-5"}


def test_default_model_is_haiku(no_key, monkeypatch):
    monkeypatch.delenv("RAMEAU_AI_MODEL", raising=False)
    assert ai.model_name() == "claude-haiku-5-5"


def test_extract_abc_from_reply():
    reply = "```abc\nX:1\nT:Test\nM:4/4\nL:1/4\nK:C\nC D E F | HG4 |]\n```\nA rising tune."
    abc = ai._extract_abc(reply)
    assert abc.startswith("X:1") and "K:C" in abc
    assert ai._extract_abc("no music here") is None


def test_friendly_error_without_key(no_key):
    with pytest.raises(ai.AIUnavailable):
        ai.ask_tutor("Why V7?", "context")
