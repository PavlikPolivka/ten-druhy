"""Thin LLM provider adapter. Gemini (free tier) by default.

Everything rate-limited (429 / RESOURCE_EXHAUSTED) is retried with backoff, which is
what makes the free tier usable for the batch ingest scripts.
"""

import random
import time
from collections.abc import Iterator

from google import genai
from google.genai import errors, types

from app import config

_client: genai.Client | None = None

NO_AFC = types.AutomaticFunctionCallingConfig(disable=True)
# Chat replies are 1-3 sentences; thinking adds ~3-10s latency on 3.x Flash for no gain.
# Not every model accepts every level, so step down through these (None = model default).
FAST_LEVELS = ["minimal", "low", None]


def _fast(call):
    """Run call(thinking_config) with the lowest thinking level the model accepts."""
    for level in FAST_LEVELS:
        try:
            return call(types.ThinkingConfig(thinking_level=level) if level else None)
        except errors.APIError as e:
            if e.code == 400 and "hinking" in str(e) and level is not None:
                continue
            raise

# The books are violent; without this, ordinary lore answers get blocked.
SAFETY = [
    types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
    for c in (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]


def client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


RETRYABLE = (429, 500, 503)
SKIP = (404,)  # model retired / not available to this key -> just try the next one


def _retry(fn, attempts: int = 8):
    for i in range(attempts):
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in RETRYABLE or i == attempts - 1:
                raise
            delay = min(120, 5 * 2**i) + random.random() * 3
            print(f"  [llm] {e.code}, retry in {delay:.0f}s", flush=True)
            time.sleep(delay)


def _chain(primary: str) -> list[str]:
    return list(dict.fromkeys([primary, *config.FALLBACK_MODELS]))


def _with_fallback(models: list[str], call, attempts: int, rounds: int = 1):
    """Try each model a few times; overloaded (503) or rate-limited (429) models fall through to the next."""
    last = None
    for r in range(rounds):
        for m in models:
            for i in range(attempts):
                try:
                    return call(m)
                except errors.APIError as e:
                    if e.code in SKIP:
                        last = e
                        print(f"  [llm] {m}: {e.code}, skipping", flush=True)
                        break
                    if e.code not in RETRYABLE:
                        raise
                    last = e
                    print(f"  [llm] {m}: {e.code} (round {r + 1}, try {i + 1})", flush=True)
                    if i < attempts - 1:
                        time.sleep(min(20, 2 * 2**i) + random.random())
        if r < rounds - 1:
            time.sleep(60)
    raise last


def _contents(history: list[dict]) -> list[types.Content]:
    """Messages may carry {"image": (bytes, mime)}; the image goes before the text like a photo with a caption."""
    out = []
    for m in history:
        parts = []
        if m.get("image"):
            data, mime = m["image"]
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        parts.append(types.Part(text=m["content"]))
        out.append(types.Content(role="model" if m["role"] == "assistant" else "user", parts=parts))
    return out


def generate(system: str, user: str, model: str | None = None, json_mode: bool = False, temperature: float = 0.3,
             patient: bool = True) -> str:
    def cfg(thinking=None):
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            safety_settings=SAFETY,
            response_mime_type="application/json" if json_mode else None,
            automatic_function_calling=NO_AFC,
            thinking_config=thinking,
        )

    def call(m):
        if patient:  # batch extraction: let the model think
            return client().models.generate_content(model=m, contents=user, config=cfg())
        return _fast(lambda t: client().models.generate_content(model=m, contents=user, config=cfg(t)))

    # Batch scripts are patient (several rounds across the chain); interactive callers fail fast.
    resp = _with_fallback(_chain(model or config.EXTRACT_MODEL), call,
                          attempts=3 if patient else 1, rounds=5 if patient else 1)
    return resp.text or ""


def stream_chat(system: str, history: list[dict], model: str | None = None) -> Iterator[str]:
    contents = _contents(history)

    def open_stream(m, thinking):
        cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.9, safety_settings=SAFETY,
                                          automatic_function_calling=NO_AFC, thinking_config=thinking)
        # Errors can surface on the first read, so pull the first chunk inside the fallback.
        stream = iter(client().models.generate_content_stream(model=m, contents=contents, config=cfg))
        return next(stream, None), stream

    def start(m):
        return _fast(lambda t: open_stream(m, t))

    # Chat is interactive: on 429/503 move to the next model immediately instead of sleeping.
    first, stream = _with_fallback(_chain(model or config.LLM_MODEL), start, attempts=1)
    if first is not None and first.text:
        yield first.text
    for chunk in stream:
        if chunk.text:
            yield chunk.text


def embed(texts: list[str], query: bool = False, retry: bool = True) -> list[list[float]]:
    cfg = types.EmbedContentConfig(
        task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
        output_dimensionality=config.EMBED_DIM,
    )
    call = lambda: client().models.embed_content(model=config.EMBED_MODEL, contents=texts, config=cfg)
    resp = _retry(call) if retry else call()
    return [e.values for e in resp.embeddings]
