"""System prompt assembly: [persona + dialogue samples + lore bible] (stable prefix) + retrieved chunks."""

import json
from functools import cache

from app import config

N_SAMPLES = 70


@cache
def stable_prefix() -> str:
    """Byte-identical across requests so Gemini's implicit prompt caching can reuse it."""
    parts = [(config.PROMPTS_DIR / "persona.md").read_text().strip()]

    dialogue = config.DERIVED_DIR / "dialogue.jsonl"
    if dialogue.exists():
        lines = [json.loads(l) for l in dialogue.open()]
        # Prefer short, punchy lines; spread evenly across the whole corpus.
        lines = [l for l in lines if 3 <= len(l["line"]) <= 220]
        step = max(1, len(lines) // N_SAMPLES)
        sample = lines[::step][:N_SAMPLES]
        parts.append("## Ukázky tvých skutečných replik (pro hlas a styl, ne k opakování)\n" + "\n".join(
            f"- ({l['situation'].strip()}) „{l['line'].strip()}“" for l in sample))

    lore = config.DERIVED_DIR / "lore_bible.md"
    if lore.exists():
        parts.append("## Lore bible\n\n" + lore.read_text().strip())
    return "\n\n".join(parts)


def system_prompt(chunks: list[dict]) -> str:
    excerpts = "\n\n".join(f"[{c['book_title']}]\n{c['text']}" for c in chunks)
    return f"{stable_prefix()}\n\n## Úryvky z knih relevantní k poslední zprávě\n\n{excerpts}"
