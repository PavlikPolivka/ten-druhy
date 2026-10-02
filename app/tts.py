"""Text-to-speech for his replies, as WAV bytes.

Chain: Gemini TTS (best voice, but free tier is 10 requests/day per model) → Piper (local Czech voice on the
server, unlimited) → caller falls back to the browser voice.
"""

import io
import re
import threading
import time
import urllib.request
import wave
from collections import OrderedDict

from google.genai import errors, types

from app import config, llm

_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = threading.Lock()
CACHE_SIZE = 32
_blocked_until: dict[str, float] = {}  # model -> epoch seconds; set when a quota is exhausted

PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{locale}/{name}/{quality}/{voice}{ext}"
_piper = None
_piper_lock = threading.Lock()


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


def _gemini(model: str, text: str) -> bytes:
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.TTS_VOICE))),
    )
    try:
        r = llm.client().models.generate_content(model=model, contents=f"{config.TTS_STYLE} {text}".strip(), config=cfg)
    except errors.APIError as e:
        if e.code == 429:
            # Daily cap → skip this model until the quota resets; per-minute cap → skip for a minute.
            m = re.search(r"retryDelay': '(\d+)s", str(e))
            _blocked_until[model] = time.time() + (int(m.group(1)) if m else 60)
        raise
    part = r.candidates[0].content.parts[0].inline_data
    return _wav(part.data, part.mime_type or "")


def _piper_voice():
    """Load the Piper voice, downloading it into the data volume on first use (kept out of the public image)."""
    global _piper
    with _piper_lock:
        if _piper is None:
            from piper import PiperVoice  # heavy import (onnxruntime); only when needed

            name = config.PIPER_VOICE  # e.g. cs_CZ-jirka-medium
            locale, speaker, quality = name.split("-")
            model = config.PIPER_DIR / f"{name}.onnx"
            config.PIPER_DIR.mkdir(parents=True, exist_ok=True)
            for ext in (".onnx", ".onnx.json"):
                dest = config.PIPER_DIR / f"{name}{ext}"
                if not dest.exists():
                    url = PIPER_URL.format(lang=locale.split("_")[0], locale=locale, name=speaker, quality=quality,
                                           voice=name, ext=ext)
                    print(f"  [tts] downloading {url}", flush=True)
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    urllib.request.urlretrieve(url, tmp)
                    tmp.rename(dest)
            _piper = PiperVoice.load(str(model))
    return _piper


def _local(text: str) -> bytes:
    from piper import SynthesisConfig

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        _piper_voice().synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=config.PIPER_LENGTH_SCALE))
    return buf.getvalue()


def synthesize(text: str) -> tuple[bytes, str]:
    """Returns (wav, engine)."""
    text = text.strip()[:1200]
    with _lock:
        if text in _cache:
            _cache.move_to_end(text)
            return _cache[text], "cache"
    audio, engine = None, None
    for model in config.TTS_MODELS:
        if _blocked_until.get(model, 0) > time.time():
            continue
        try:
            audio, engine = _gemini(model, text), model
            break
        except (errors.APIError, AttributeError, IndexError, TypeError) as e:
            print(f"  [tts] {model}: {str(e)[:80]}", flush=True)
    if audio is None and config.PIPER_VOICE:
        audio, engine = _local(text), "piper"
    if audio is None:
        raise RuntimeError("no tts engine available")
    with _lock:
        _cache[text] = audio
        if len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return audio, engine
