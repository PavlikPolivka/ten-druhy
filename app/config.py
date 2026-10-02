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

QDRANT_URL = os.getenv("QDRANT_URL", "")  # empty -> embedded local Qdrant at data/qdrant
QDRANT_PATH = ROOT / "data" / "qdrant"
COLLECTION = os.getenv("COLLECTION", "kulhanek")

DERIVED_DIR = Path(os.getenv("DERIVED_DIR", ROOT / "data" / "derived"))
PROMPTS_DIR = ROOT / "prompts"
SESSIONS_DB = Path(os.getenv("SESSIONS_DB", ROOT / "data" / "sessions.sqlite"))
PIPER_DIR = Path(os.getenv("PIPER_DIR", SESSIONS_DB.parent / "piper"))

TOP_K = int(os.getenv("TOP_K", "6"))
HISTORY_TOKENS = int(os.getenv("HISTORY_TOKENS", "8000"))
