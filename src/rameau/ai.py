"""Optional AI mode (bring your own key): a harmony tutor and a melody composer, powered by Claude.

Rameau works fully without AI. To turn it on, provide an Anthropic API key in one of these ways
(first match wins):

1. the ``ANTHROPIC_API_KEY`` environment variable (or any credential the Anthropic SDK finds on
   its own, such as an ``ant auth login`` profile), or
2. the operating system's keychain, saved from the app's AI settings (macOS Keychain, Windows
   Credential Manager, Linux Secret Service).

Keys are never written to Rameau's files or to the repository. The model name is a plain setting
(default: Claude Haiku) and is stored in the user's settings file.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

DEFAULT_MODEL = "claude-haiku-5-5"
KEYCHAIN_SERVICE = "rameau-studio"
LEGACY_KEYCHAIN_USER = "anthropic-api-key"   # single key saved by earlier versions
ENV_PROFILE = "Environment variable"

# Shown when the live model list can't be fetched (no key yet, offline). Cheapest first.
FALLBACK_MODELS = [
    ("claude-haiku-5-5", "Claude Haiku 5.5 (fast, inexpensive)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 (balanced)"),
    ("claude-opus-5-5", "Claude Opus 5.5 (most thorough)"),
]


class AIUnavailable(RuntimeError):
    """AI mode can't run (no key, bad key, no network...). The message is safe to show the user."""


# --------------------------------------------------------------------------- settings

def _settings_path():
    from .audio import user_data_dir

    return user_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    # Never persist secrets here: drop anything that looks like a key value.
    clean = {k: v for k, v in settings.items() if "key" not in k.lower() and not str(v).startswith("sk-")}
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=1), encoding="utf-8")


def model_name() -> str:
    return os.environ.get("RAMEAU_AI_MODEL") or load_settings().get("ai_model") or DEFAULT_MODEL


def set_model(model: str) -> None:
    settings = load_settings()
    settings["ai_model"] = model.strip() or DEFAULT_MODEL
    save_settings(settings)


# --------------------------------------------------------------------------- API key profiles
#
# A profile is a name (e.g. "Personal", "Work"). Its key lives in the OS keychain under
# "anthropic-api-key:<name>". The environment variable, when set, appears as its own profile.
# Settings store only the profile names and which one is active.

def _keyring():
    import keyring

    return keyring


def _keychain_user(profile: str) -> str:
    return f"anthropic-api-key:{profile}"


def _migrate_legacy_key() -> None:
    try:
        old = _keyring().get_password(KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_USER)
    except Exception:
        return
    if old:
        add_profile("Default", old, activate=not load_settings().get("ai_active_profile"))
        try:
            _keyring().delete_password(KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_USER)
        except Exception:
            pass


def env_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def list_profiles() -> list[str]:
    _migrate_legacy_key()
    names = list(load_settings().get("ai_profiles", []))
    return ([ENV_PROFILE] if env_key_present() else []) + names


def active_profile() -> str | None:
    profiles = list_profiles()
    chosen = load_settings().get("ai_active_profile")
    if chosen in profiles:
        return chosen
    return profiles[0] if profiles else None


def set_active_profile(name: str) -> None:
    settings = load_settings()
    settings["ai_active_profile"] = name
    save_settings(settings)


def add_profile(name: str, api_key: str, activate: bool = True) -> None:
    name = name.strip()
    if not name or name == ENV_PROFILE:
        raise ValueError("Choose a name for this key, e.g. Personal or Work.")
    if not api_key.strip():
        raise ValueError("Paste the API key.")
    _keyring().set_password(KEYCHAIN_SERVICE, _keychain_user(name), api_key.strip())
    settings = load_settings()
    names = [n for n in settings.get("ai_profiles", []) if n != name] + [name]
    settings["ai_profiles"] = names
    if activate:
        settings["ai_active_profile"] = name
    save_settings(settings)


def remove_profile(name: str) -> None:
    if name == ENV_PROFILE:
        raise ValueError("The environment key is set outside Rameau; unset ANTHROPIC_API_KEY to remove it.")
    try:
        _keyring().delete_password(KEYCHAIN_SERVICE, _keychain_user(name))
    except Exception:
        pass
    settings = load_settings()
    settings["ai_profiles"] = [n for n in settings.get("ai_profiles", []) if n != name]
    if settings.get("ai_active_profile") == name:
        settings.pop("ai_active_profile", None)
    save_settings(settings)


def profile_key(name: str) -> str | None:
    if name == ENV_PROFILE:
        return None
    try:
        return _keyring().get_password(KEYCHAIN_SERVICE, _keychain_user(name))
    except Exception:
        return None


def key_source() -> str | None:
    """Name of the profile in use, or None if AI mode is off."""
    return active_profile()


def _client(profile: str | None = None):
    import anthropic

    profile = profile or active_profile()
    if profile is None:
        raise AIUnavailable("AI mode is off: add an Anthropic API key in AI settings, or set the "
                            "ANTHROPIC_API_KEY environment variable.")
    try:
        if profile == ENV_PROFILE:
            return anthropic.Anthropic()
        key = profile_key(profile)
        if not key:
            raise AIUnavailable(f"No key is saved for '{profile}'. Add it again in AI settings.")
        return anthropic.Anthropic(api_key=key)
    except AIUnavailable:
        raise
    except Exception as e:
        raise AIUnavailable("AI mode is off: add an Anthropic API key in AI settings, or set the "
                            "ANTHROPIC_API_KEY environment variable.") from e


def list_models(profile: str | None = None) -> list[tuple[str, str]]:
    """Models this key can use, as (id, display name), from Anthropic's Models API (no token cost).

    Raises AIUnavailable with a friendly message if the key is missing or rejected.
    """
    import anthropic

    client = _client(profile)
    try:
        models = [(m.id, m.display_name) for m in client.models.list()]
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("This API key was rejected.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Couldn't reach Anthropic. Check your internet connection.") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"Couldn't list models ({e.status_code}).") from e
    # Haiku first (the default), then Sonnet, Opus, everything else; newest first within each.
    order = {"haiku": 0, "sonnet": 1, "opus": 2}
    models.sort(key=lambda m: m[0], reverse=True)  # newest first within a family...
    return sorted(models, key=lambda m: next((v for k, v in order.items() if k in m[0]), 3))  # ...Haiku first


def _error_detail(e) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return str(body.get("error", {}).get("message") or e.message)
    return str(getattr(e, "message", e))


def _ask(system: str, messages: list[dict], max_tokens: int = 4000) -> str:
    import anthropic

    client = _client()
    try:
        response = client.messages.create(
            model=model_name(),
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": "low"},
        )
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("The API key was rejected. Check it in AI settings.") from e
    except anthropic.PermissionDeniedError as e:
        raise AIUnavailable("This API key isn't allowed to use that model.") from e
    except anthropic.NotFoundError as e:
        raise AIUnavailable(f"Unknown model '{model_name()}'. Check the model name in AI settings.") from e
    except anthropic.RateLimitError as e:
        raise AIUnavailable("Rate limited by the API. Wait a moment and try again.") from e
    except anthropic.BadRequestError as e:
        detail = _error_detail(e)
        if "credit balance" in detail.lower():
            raise AIUnavailable("Your Anthropic account is out of API credits. Add credits under Plans & "
                                "Billing at console.anthropic.com, then try again.") from e
        raise AIUnavailable(f"The AI request was rejected: {detail}") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"The AI service had a problem ({e.status_code}). Try again later.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Couldn't reach the AI service. Check your internet connection.") from e
    except anthropic.AnthropicError as e:
        raise AIUnavailable("AI mode is off: add an Anthropic API key in AI settings, or set the "
                            "ANTHROPIC_API_KEY environment variable.") from e
    if response.stop_reason == "refusal":
        raise AIUnavailable("The model declined this request. Try rephrasing it.")
    return "".join(b.text for b in response.content if b.type == "text").strip()


# --------------------------------------------------------------------------- tutor

TUTOR_SYSTEM = """You are the tutor inside Rameau Studio, an app that teaches how harmony creates the \
signature sound of a composer, style or era. The learner may be a beginner: explain in plain, warm \
language, define any theory term the first time you use it, and keep answers short (a few short \
paragraphs or a list) unless asked for more.

You are given Rameau's own analysis of the piece on screen: the chosen chords with Roman numerals, \
the statistics the style was learned from, voice-leading findings, and style fingerprints. Ground \
your answers in that analysis and quote its numbers when they help. If the analysis doesn't support \
a claim, say you're reasoning from general music theory. Never invent statistics. When useful, \
suggest one concrete experiment the learner can try in the app (lock a different chord, switch \
style or sound, compare fingerprints)."""


@dataclass
class TutorTurn:
    role: str  # "user" or "assistant"
    text: str


def ask_tutor(question: str, context: str, history: list[TutorTurn] | None = None) -> str:
    """Answer a question about the current piece, grounded in Rameau's analysis (``context``)."""
    messages: list[dict] = [{"role": "user", "content": f"Rameau's analysis of the current piece:\n\n{context}"},
                            {"role": "assistant", "content": "Thanks, I've read the analysis. What would you like "
                                                             "to know?"}]
    for turn in history or []:
        messages.append({"role": turn.role, "content": turn.text})
    messages.append({"role": "user", "content": question})
    return _ask(TUTOR_SYSTEM, messages, max_tokens=2000)


# --------------------------------------------------------------------------- composer

COMPOSER_SYSTEM = """You write melodies in ABC notation for Rameau Studio, which will harmonize them. \
Write a single-line melody only (no chords, no lyrics, no multiple voices). Rules:
- Include the headers X:1, T:, M:, L:, K: and nothing else in the header.
- Keep it singable: mostly steps, few leaps larger than a fifth, range within about an octave and a half.
- Mark the end of each phrase with a fermata: put H directly before the note (e.g. HG2).
- End on the home note of the key.
Reply with only the ABC inside one ```abc code block, then one sentence describing the melody."""


def _extract_abc(text: str) -> str | None:
    m = re.search(r"```(?:abc)?\s*\n(.*?)```", text, re.S)
    body = m.group(1) if m else text
    return body.strip() if re.search(r"^K:", body, re.M) else None


def compose_melody(request: str, style_title: str = "", bars: int = 8) -> tuple[str, str]:
    """Ask the model for a melody. Returns (ABC text, one-sentence description).

    The ABC is checked by parsing it with Rameau's own loader; one repair attempt is made if it fails.
    """
    from .music import load_melody

    prompt = (f"Write a melody of about {bars} bars. Request: {request.strip() or 'a simple hymn-like tune'}."
              + (f" It will be harmonized in the style of {style_title}, so suit that era." if style_title else ""))
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(2):
        reply = _ask(COMPOSER_SYSTEM, messages, max_tokens=3000)
        abc = _extract_abc(reply)
        problem = "No ABC code block was found." if abc is None else None
        if abc is not None:
            try:
                part = load_melody(abc)
                if not list(part.flatten().notes):
                    problem = "The ABC has no notes."
            except Exception as e:
                problem = f"The ABC didn't parse: {e}"
        if problem is None:
            description = re.sub(r"```.*?```", "", reply, flags=re.S).strip()
            return abc, description
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"{problem} Please send corrected ABC in one ```abc block."}]
    raise AIUnavailable("The AI couldn't produce a melody Rameau could read. Try a simpler request.")
