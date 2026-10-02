import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "gemini-flash-lite-latest")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

QDRANT_URL = os.getenv("QDRANT_URL", "")  # empty -> embedded local Qdrant at data/qdrant
QDRANT_PATH = ROOT / "data" / "qdrant"
COLLECTION = os.getenv("COLLECTION", "kulhanek")

DERIVED_DIR = Path(os.getenv("DERIVED_DIR", ROOT / "data" / "derived"))
PROMPTS_DIR = ROOT / "prompts"
SESSIONS_DB = Path(os.getenv("SESSIONS_DB", ROOT / "data" / "sessions.sqlite"))

TOP_K = int(os.getenv("TOP_K", "6"))
HISTORY_TOKENS = int(os.getenv("HISTORY_TOKENS", "8000"))
