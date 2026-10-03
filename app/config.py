import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "gemini-flash-lite-latest")
# Each model has its own free-tier quota, so a long chain multiplies free capacity.
# Ordered by how well the model holds the persona voice (Flash-Lite beats 3.5-flash there), not by size.
FALLBACK_MODELS = [m for m in os.getenv("FALLBACK_MODELS", "gemini-3.6-flash,gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.7-flash,gemini-3.1-flash-lite").split(",") if m]
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

# Gemini TTS (free tier: ~3 requests/min per model). No style prompt by default: any instruction prefix either gets
# read aloud (2.5) or pushes the model into an English accent ("rvat" instead of "řvát"); plain text is fluent Czech.
# Off by default (10 requests/day isn't worth it): read-aloud uses the local Piper voice only.
# Set e.g. TTS_MODELS=gemini-3.8-flash-tts to put Gemini back in front of Piper.
TTS_MODELS = [m for m in os.getenv("TTS_MODELS", "").split(",") if m]
TTS_VOICE = os.getenv("TTS_VOICE", "Charon")
TTS_STYLE = os.getenv("TTS_STYLE", "")

# Local Czech voice (Piper, CC0 dataset) after Gemini TTS runs out; empty PIPER_VOICE disables it.
PIPER_VOICE = os.getenv("PIPER_VOICE", "cs_CZ-jirka-medium")
PIPER_LENGTH_SCALE = float(os.getenv("PIPER_LENGTH_SCALE", "0.9"))  # <1 = faster

# Proactive check-ins via Web Push (scheduler thread in the app). VAPID "sub" claim must be mailto: or https URL.
CHECKINS = os.getenv("CHECKINS", "1") == "1"
PUSH_CONTACT = os.getenv("PUSH_CONTACT", "https://druhy.ppolivka.com")

# Per-person tone pinned server-side, e.g. TONE_LOCK=elenka:kid,babicka:mild (Authelia usernames).
TONE_LOCK = dict(p.split(":", 1) for p in os.getenv("TONE_LOCK", "").split(",") if ":" in p)

# Shared secret Caddy adds as X-TD-Proxy; when set, only /v1 and /healthz work without it. Empty = off.
PROXY_SECRET = os.getenv("TD_PROXY_SECRET", "")

# Admins (Authelia usernames): homelab watchdog alerts + server tools.
ADMIN_USERS = [u for u in os.getenv("ADMIN_USERS", "pavel").split(",") if u]

# Public base URL (links in announcements / audio clips for Twilio).
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://druhy.ppolivka.com").rstrip("/")

# Home for weather questions without a place, and the morning brief.
HOME_PLACE = os.getenv("HOME_PLACE", "Buštěhrad")

QDRANT_URL = os.getenv("QDRANT_URL", "")  # empty -> embedded local Qdrant at data/qdrant
QDRANT_PATH = ROOT / "data" / "qdrant"
COLLECTION = os.getenv("COLLECTION", "kulhanek")

DERIVED_DIR = Path(os.getenv("DERIVED_DIR", ROOT / "data" / "derived"))
PROMPTS_DIR = ROOT / "prompts"
SESSIONS_DB = Path(os.getenv("SESSIONS_DB", ROOT / "data" / "sessions.sqlite"))
PIPER_DIR = Path(os.getenv("PIPER_DIR", SESSIONS_DB.parent / "piper"))
HOST_JSON = Path(os.getenv("HOST_JSON", SESSIONS_DB.parent / "host.json"))  # written by host/tendruhy-hoststatus.py

TOP_K = int(os.getenv("TOP_K", "6"))
HISTORY_TOKENS = int(os.getenv("HISTORY_TOKENS", "8000"))
