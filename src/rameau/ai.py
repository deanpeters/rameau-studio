"""Optional AI mode (bring your own key): a harmony tutor and a melody composer.

Rameau works fully without AI. Two providers are supported:

* **Anthropic** (Claude; default model Claude Haiku 5.5)
* **OpenAI**, or any OpenAI-compatible server (OpenRouter, a local Ollama or LM Studio) via a
  custom server address

Keys come from environment variables (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``), which appear as
their own entries, or from named keys saved in the operating system's keychain (macOS Keychain,
Windows Credential Manager, Linux Secret Service). Keys are never written to Rameau's files or to
the repository. The settings file stores only key names, providers, server addresses and models.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

DEFAULT_MODEL = "claude-haiku-5-5"
KEYCHAIN_SERVICE = "rameau-studio"
LEGACY_KEYCHAIN_USER = "anthropic-api-key"   # single key saved by the first version

ANTHROPIC, OPENAI = "anthropic", "openai"
PROVIDER_NAMES = {ANTHROPIC: "Anthropic (Claude)", OPENAI: "OpenAI or compatible"}
ENV_ANTHROPIC = "Anthropic (environment variable)"
ENV_OPENAI = "OpenAI (environment variable)"
ENV_PROFILE = ENV_ANTHROPIC  # kept for compatibility

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
    def safe(v):
        return not (isinstance(v, str) and (v.startswith("sk-") or v.startswith("sk_")))

    clean = {k: v for k, v in settings.items() if "key" not in k.lower() and safe(v)}
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- key profiles
#
# A profile is a named key: {"name", "provider", "base_url"}. Its secret lives in the keychain under
# "<provider>-api-key:<name>". Environment variables appear as built-in profiles.

def _keyring():
    import keyring

    return keyring


def _keychain_user(profile: str, provider: str = ANTHROPIC) -> str:
    return f"{provider}-api-key:{profile}"


def _saved_profiles(settings: dict | None = None) -> list[dict]:
    settings = load_settings() if settings is None else settings
    out = []
    for p in settings.get("ai_profiles", []):
        if isinstance(p, str):  # the first version stored plain names (all Anthropic)
            p = {"name": p, "provider": ANTHROPIC, "base_url": None}
        out.append({"name": p["name"], "provider": p.get("provider", ANTHROPIC), "base_url": p.get("base_url")})
    return out


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


def env_key_present(provider: str = ANTHROPIC) -> bool:
    if provider == OPENAI:
        return bool(os.environ.get("OPENAI_API_KEY"))
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def list_profiles() -> list[str]:
    _migrate_legacy_key()
    names = [p["name"] for p in _saved_profiles()]
    env = ([ENV_ANTHROPIC] if env_key_present(ANTHROPIC) else []) + ([ENV_OPENAI] if env_key_present(OPENAI) else [])
    return env + names


def profile_info(name: str) -> dict:
    """{"name", "provider", "base_url"} for a profile."""
    if name == ENV_ANTHROPIC:
        return {"name": name, "provider": ANTHROPIC, "base_url": None}
    if name == ENV_OPENAI:
        return {"name": name, "provider": OPENAI, "base_url": os.environ.get("OPENAI_BASE_URL")}
    for p in _saved_profiles():
        if p["name"] == name:
            return p
    raise AIUnavailable(f"No saved key called '{name}'.")


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


def add_profile(name: str, api_key: str, activate: bool = True, provider: str = ANTHROPIC,
                base_url: str | None = None) -> None:
    name = name.strip()
    if not name or name in (ENV_ANTHROPIC, ENV_OPENAI):
        raise ValueError("Choose a name for this key, e.g. Personal or Work.")
    if not api_key.strip() and not base_url:
        raise ValueError("Paste the API key.")
    if provider not in PROVIDER_NAMES:
        raise ValueError(f"Unknown provider '{provider}'.")
    _keyring().set_password(KEYCHAIN_SERVICE, _keychain_user(name, provider), api_key.strip() or "none")
    settings = load_settings()
    profiles = [p for p in _saved_profiles(settings) if p["name"] != name]
    profiles.append({"name": name, "provider": provider, "base_url": (base_url or "").strip() or None})
    settings["ai_profiles"] = profiles
    if activate:
        settings["ai_active_profile"] = name
    save_settings(settings)


def remove_profile(name: str) -> None:
    if name in (ENV_ANTHROPIC, ENV_OPENAI):
        raise ValueError("Environment keys are set outside Rameau; unset the environment variable to remove it.")
    info = next((p for p in _saved_profiles() if p["name"] == name), None)
    if info:
        try:
            _keyring().delete_password(KEYCHAIN_SERVICE, _keychain_user(name, info["provider"]))
        except Exception:
            pass
    settings = load_settings()
    settings["ai_profiles"] = [p for p in _saved_profiles(settings) if p["name"] != name]
    settings.get("ai_models", {}).pop(name, None)
    if settings.get("ai_active_profile") == name:
        settings.pop("ai_active_profile", None)
    save_settings(settings)


def profile_key(name: str) -> str | None:
    if name in (ENV_ANTHROPIC, ENV_OPENAI):
        return None
    try:
        info = profile_info(name)
        return _keyring().get_password(KEYCHAIN_SERVICE, _keychain_user(name, info["provider"]))
    except Exception:
        return None


def key_source() -> str | None:
    """Name of the profile in use, or None if AI mode is off."""
    return active_profile()


def provider_of(profile: str | None = None) -> str | None:
    profile = profile or active_profile()
    return profile_info(profile)["provider"] if profile else None


# --------------------------------------------------------------------------- models (one per key)

def model_name(profile: str | None = None) -> str:
    """The model chosen for this key (default Claude Haiku for Anthropic; for OpenAI, resolved on first use)."""
    if os.environ.get("RAMEAU_AI_MODEL"):
        return os.environ["RAMEAU_AI_MODEL"]
    profile = profile or active_profile()
    settings = load_settings()
    chosen = settings.get("ai_models", {}).get(profile) if profile else None
    if chosen:
        return chosen
    if profile and provider_of(profile) == OPENAI:
        return ""
    return settings.get("ai_model") or DEFAULT_MODEL


def set_model(model: str, profile: str | None = None) -> None:
    profile = profile or active_profile()
    settings = load_settings()
    if profile:
        settings.setdefault("ai_models", {})[profile] = model.strip()
    else:
        settings["ai_model"] = model.strip() or DEFAULT_MODEL
    save_settings(settings)


# --------------------------------------------------------------------------- clients

def _client(profile: str | None = None):
    """An SDK client for the profile: anthropic.Anthropic or openai.OpenAI."""
    profile = profile or active_profile()
    if profile is None:
        raise AIUnavailable("AI mode is off: add an API key in AI settings, or set ANTHROPIC_API_KEY or "
                            "OPENAI_API_KEY.")
    info = profile_info(profile)
    if info["provider"] == OPENAI:
        from .ai_openai import make_client

        key = None if profile == ENV_OPENAI else profile_key(profile)
        if profile != ENV_OPENAI and not key:
            raise AIUnavailable(f"No key is saved for '{profile}'. Add it again in AI settings.")
        return make_client(key, info.get("base_url"))
    import anthropic

    try:
        if profile == ENV_ANTHROPIC:
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
    """Models this key can use, as (id, display name). Listing models costs nothing."""
    profile = profile or active_profile()
    client = _client(profile)
    if provider_of(profile) == OPENAI:
        from .ai_openai import list_models as openai_models

        return openai_models(client)
    import anthropic

    try:
        models = [(m.id, m.display_name) for m in client.models.list()]
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("This API key was rejected.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Couldn't reach Anthropic. Check your internet connection.") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"Couldn't list models ({e.status_code}).") from e
    order = {"haiku": 0, "sonnet": 1, "opus": 2}
    models.sort(key=lambda m: m[0], reverse=True)  # newest first within a family...
    return sorted(models, key=lambda m: next((v for k, v in order.items() if k in m[0]), 3))  # ...Haiku first


def _error_detail(e) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return str(body.get("error", {}).get("message") or e.message)
    return str(getattr(e, "message", e))


def _ask(system: str, messages: list[dict], max_tokens: int = 4000) -> str:
    profile = active_profile()
    client = _client(profile)
    if provider_of(profile) == OPENAI:
        from .ai_openai import ask, default_model

        model = model_name(profile)
        if not model:
            model = default_model(client)
            if not model:
                raise AIUnavailable("No chat models are available to this OpenAI key.")
            set_model(model, profile)
        return ask(client, model, system, messages, max_tokens=max(max_tokens, 4000))
    import anthropic

    try:
        response = client.messages.create(
            model=model_name(profile),
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
        raise AIUnavailable(f"Unknown model '{model_name(profile)}'. Check the model name in AI settings.") from e
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
