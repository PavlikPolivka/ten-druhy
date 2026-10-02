import json
import re

from app import config
from ingest.books import TEXT

CACHE = config.DERIVED_DIR / "cache"
TD = re.compile(r"(?i)\bten,? druh[ýy]|\btím druhým|\btoho druhého|\btomu druhému")


def load_sections():
    return [json.loads(l) for l in (TEXT / "sections.jsonl").open()]


def prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text()


def cached(task: str, key: str, fn, suffix: str = ".txt") -> str:
    """Run fn() once per (task, key); results persist so interrupted runs resume."""
    path = CACHE / task / (key.replace(":", "_") + suffix)
    if path.exists():
        return path.read_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = fn()
    path.write_text(out)
    return out
