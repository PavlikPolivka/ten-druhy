"""System prompt assembly: [persona + dialogue samples + lore bible] (stable prefix) + per-request tail."""

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
        # Short, punchy lines spread across the corpus. No situations: they drag book characters into replies.
        lines = [l for l in lines if 3 <= len(l["line"]) <= 160]
        step = max(1, len(lines) // N_SAMPLES)
        sample = lines[::step][:N_SAMPLES]
        parts.append("## Ukázky tvých replik (jen pro tón a styl – neopakuj je, nenavazuj na jejich obsah)\n"
                     + "\n".join(f"- „{l['line'].strip()}“" for l in sample))

    lore = config.DERIVED_DIR / "lore_bible.md"
    if lore.exists():
        parts.append("## Lore bible (tvoje paměť – používej jen když na to přijde řeč)\n\n" + lore.read_text().strip())
    return "\n\n".join(parts)


def system_prompt(chunks: list[dict], user_name: str = "") -> str:
    tail = []
    if user_name:
        tail.append(f"## S kým mluvíš\nPíše ti **{user_name}**. Oslovuj ho/ji jménem jen občas, přirozeně.")
    if chunks:
        excerpts = "\n\n".join(f"[{c['book_title']}]\n{c['text']}" for c in chunks)
        tail.append(f"## Úryvky z knih k aktuální otázce\n\n{excerpts}")
    return "\n\n".join([stable_prefix(), *tail])
