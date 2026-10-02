"""Gemini text-to-speech for his replies. Returns WAV bytes; callers fall back to the browser voice on failure."""

import io
import threading
import wave
from collections import OrderedDict

from google.genai import errors, types

from app import config, llm

_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = threading.Lock()
CACHE_SIZE = 32


def _wav(data: bytes, mime: str) -> bytes:
    """3.8 returns a WAV file; older models return raw 16-bit PCM (audio/L16;rate=24000)."""
    if data[:4] == b"RIFF":
        return data
    rate = 24000
    for part in mime.split(";"):
        if part.strip().startswith("rate="):
            rate = int(part.split("=")[1])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)
    return buf.getvalue()


def synthesize(text: str) -> bytes:
    text = text.strip()[:1200]
    with _lock:
        if text in _cache:
            _cache.move_to_end(text)
            return _cache[text]
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.TTS_VOICE))),
    )
    last = None
    for model in config.TTS_MODELS:  # each model has its own 3/min quota
        try:
            r = llm.client().models.generate_content(model=model, contents=f"{config.TTS_STYLE} {text}", config=cfg)
            part = r.candidates[0].content.parts[0].inline_data
            audio = _wav(part.data, part.mime_type or "")
            with _lock:
                _cache[text] = audio
                if len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
            return audio
        except (errors.APIError, AttributeError, IndexError, TypeError) as e:
            last = e
            print(f"  [tts] {model}: {str(e)[:80]}", flush=True)
    raise RuntimeError(f"tts failed: {last}")
