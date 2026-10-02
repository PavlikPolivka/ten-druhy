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


def _retry(fn, attempts: int = 8):
    for i in range(attempts):
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in (429, 500, 503) or i == attempts - 1:
                raise
            delay = min(120, 5 * 2**i) + random.random() * 3
            print(f"  [llm] {e.code}, retry in {delay:.0f}s", flush=True)
            time.sleep(delay)


def _contents(history: list[dict]) -> list[types.Content]:
    return [
        types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
        for m in history
    ]


def generate(system: str, user: str, model: str | None = None, json_mode: bool = False, temperature: float = 0.3) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        safety_settings=SAFETY,
        response_mime_type="application/json" if json_mode else None,
    )
    resp = _retry(lambda: client().models.generate_content(model=model or config.EXTRACT_MODEL, contents=user, config=cfg))
    return resp.text or ""


def stream_chat(system: str, history: list[dict], model: str | None = None) -> Iterator[str]:
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.9, safety_settings=SAFETY)
    stream = _retry(lambda: client().models.generate_content_stream(
        model=model or config.LLM_MODEL, contents=_contents(history), config=cfg))
    for chunk in stream:
        if chunk.text:
            yield chunk.text


def embed(texts: list[str], query: bool = False) -> list[list[float]]:
    cfg = types.EmbedContentConfig(
        task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
        output_dimensionality=config.EMBED_DIM,
    )
    resp = _retry(lambda: client().models.embed_content(model=config.EMBED_MODEL, contents=texts, config=cfg))
    return [e.values for e in resp.embeddings]
