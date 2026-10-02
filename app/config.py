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

# Gemini TTS (free tier: ~3 requests/min per model). Voice picked from samples; style prompt must be English
# (a Czech instruction gets read aloud).
TTS_MODELS = [m for m in os.getenv("TTS_MODELS", "gemini-3.8-flash-tts,gemini-2.5-flash-preview-tts").split(",") if m]
TTS_VOICE = os.getenv("TTS_VOICE", "Charon")
TTS_STYLE = os.getenv("TTS_STYLE", "Say at a brisk pace, in a dry, cynical, deadpan, deep gravelly male voice:")

QDRANT_URL = os.getenv("QDRANT_URL", "")  # empty -> embedded local Qdrant at data/qdrant
QDRANT_PATH = ROOT / "data" / "qdrant"
COLLECTION = os.getenv("COLLECTION", "kulhanek")

DERIVED_DIR = Path(os.getenv("DERIVED_DIR", ROOT / "data" / "derived"))
PROMPTS_DIR = ROOT / "prompts"
SESSIONS_DB = Path(os.getenv("SESSIONS_DB", ROOT / "data" / "sessions.sqlite"))

TOP_K = int(os.getenv("TOP_K", "6"))
HISTORY_TOKENS = int(os.getenv("HISTORY_TOKENS", "8000"))
