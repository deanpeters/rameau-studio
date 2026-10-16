"""OpenAI (and OpenAI-compatible) provider for AI mode.

Kept separate from the Anthropic code in ai.py. Works with OpenAI itself and with services that
offer an OpenAI-compatible API (OpenRouter, a local Ollama or LM Studio server) via ``base_url``.
"""

from __future__ import annotations

import re

# Model families that aren't for chat (speech, images, embeddings, search, realtime...).
_NOT_CHAT = re.compile(r"(embed|whisper|tts|transcribe|audio|realtime|image|dall-e|moderation|search|"
                       r"davinci|babbage|computer-use|codex|sora)", re.I)
_CHAT = re.compile(r"^(gpt-|o\d|chatgpt)", re.I)


def make_client(api_key: str | None, base_url: str | None = None):
    import openai

    from .ai import AIUnavailable

    try:
        # api_key=None lets the SDK read OPENAI_API_KEY from the environment.
        return openai.OpenAI(api_key=api_key, base_url=base_url or None)
    except openai.OpenAIError as e:
        raise AIUnavailable("No OpenAI key found: add one in AI settings, or set OPENAI_API_KEY.") from e


def _friendly(e) -> "Exception":
    import openai

    from .ai import AIUnavailable

    body = getattr(e, "body", None)
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(e, openai.AuthenticationError):
        return AIUnavailable("The OpenAI key was rejected. Check it in AI settings.")
    if isinstance(e, openai.PermissionDeniedError):
        return AIUnavailable("This OpenAI key isn't allowed to use that model.")
    if isinstance(e, openai.NotFoundError):
        return AIUnavailable("That model isn't available to this OpenAI key. Pick another in AI settings.")
    if isinstance(e, openai.RateLimitError):
        if code == "insufficient_quota":
            return AIUnavailable("Your OpenAI account is out of credits or over its quota. Check billing at "
                                 "platform.openai.com, then try again.")
        return AIUnavailable("Rate limited by OpenAI. Wait a moment and try again.")
    if isinstance(e, openai.BadRequestError):
        return AIUnavailable(f"The AI request was rejected: {getattr(e, 'message', e)}")
    if isinstance(e, openai.APIConnectionError):
        return AIUnavailable("Couldn't reach the AI service. Check your internet connection (or the server address).")
    if isinstance(e, openai.APIStatusError):
        return AIUnavailable(f"The AI service had a problem ({e.status_code}). Try again later.")
    return AIUnavailable(f"AI request failed: {e}")


def list_models(client) -> list[tuple[str, str]]:
    """Chat models available to this key, as (id, display name); cheaper 'mini' models first."""
    import openai

    try:
        ids = [m.id for m in client.models.list()]
    except openai.OpenAIError as e:
        raise _friendly(e) from e
    chat = [i for i in ids if not _NOT_CHAT.search(i) and (_CHAT.search(i) or "/" in i or ":" in i)]
    if not chat:  # OpenAI-compatible servers (e.g. Ollama) use their own model names
        chat = ids
    def rank(model_id: str):
        # Newest GPT generation first (gpt-5.4 > gpt-5 > gpt-4.1), cheaper "mini" models first within it,
        # undated aliases before dated snapshots; then o-series and others.
        m = re.match(r"gpt-(\d+(?:\.\d+)?)", model_id)
        version = float(m.group(1)) if m else -1.0
        dated = bool(re.search(r"-\d{4}-\d{2}-\d{2}$", model_id))
        return (0 if m else 1, -version, 0 if "mini" in model_id else 1, dated, model_id)

    chat.sort(key=rank)
    return [(i, i) for i in chat]


def default_model(client) -> str | None:
    """The newest GPT 'mini' model (inexpensive and fast), else the first chat model."""
    models = [m for m, _ in list_models(client)]
    minis = [m for m in models if "mini" in m and not re.search(r"-\d{4}-\d{2}-\d{2}$", m)]
    return (minis or models or [None])[0]


def ask(client, model: str, system: str, messages: list[dict], max_tokens: int = 4000) -> str:
    import openai

    from .ai import AIUnavailable

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}] + messages,
            max_completion_tokens=max_tokens,
        )
    except openai.OpenAIError as e:
        raise _friendly(e) from e
    choice = response.choices[0] if response.choices else None
    if choice is None:
        raise AIUnavailable("The model returned no answer. Try again.")
    if choice.finish_reason == "content_filter":
        raise AIUnavailable("The model declined this request. Try rephrasing it.")
    text = (choice.message.content or "").strip()
    if not text:
        raise AIUnavailable("The model returned an empty answer (it may have run out of room to think). "
                            "Try again or pick a different model.")
    return text
