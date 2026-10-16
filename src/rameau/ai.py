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
KEYCHAIN_USER = "anthropic-api-key"


class AIUnavailable(RuntimeError):
    """AI mode can't run (no key, bad key, no network...). The message is safe to show the user."""


# --------------------------------------------------------------------------- settings & keys

def _settings_path():
    from .audio import user_data_dir

    return user_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text())
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    clean = {k: v for k, v in settings.items() if "key" not in k.lower()}  # never persist secrets here
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=1))


def model_name() -> str:
    return os.environ.get("RAMEAU_AI_MODEL") or load_settings().get("ai_model") or DEFAULT_MODEL


def keychain_key() -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_USER)
    except Exception:
        return None


def save_key_to_keychain(api_key: str) -> None:
    import keyring

    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_USER, api_key.strip())


def clear_keychain_key() -> None:
    try:
        import keyring

        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_USER)
    except Exception:
        pass


def key_source() -> str | None:
    """Where the key comes from ('environment' / 'keychain'), or None if AI mode is off."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "environment"
    if keychain_key():
        return "keychain"
    return None


def _client():
    import anthropic

    try:
        # Environment variables (and SDK auth profiles) take priority; the keychain is the fallback.
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return anthropic.Anthropic()
        key = keychain_key()
        return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    except Exception as e:
        raise AIUnavailable("AI mode is off: add an Anthropic API key in AI settings, or set the "
                            "ANTHROPIC_API_KEY environment variable.") from e


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
