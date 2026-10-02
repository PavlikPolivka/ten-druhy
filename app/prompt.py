"""System prompt assembly: [persona + dialogue samples + lore bible] (stable prefix) + per-request tail."""

import json
import re
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo

from app import config

N_SAMPLES = 60
TZ = ZoneInfo("Europe/Prague")
DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října",
          "listopadu", "prosince"]


def now_line(now: datetime | None = None) -> str:
    now = now or datetime.now(TZ)
    part = ("noc" if now.hour < 5 else "ráno" if now.hour < 9 else "dopoledne" if now.hour < 12 else
            "odpoledne" if now.hour < 18 else "večer" if now.hour < 22 else "noc")
    return f"{DAYS[now.weekday()]} {now.day}. {MONTHS[now.month - 1]} {now.year}, {now:%H:%M} ({part})"
# A capitalized word after the first one = probably a character/place name; skip those samples.
NAME = re.compile(r"(?<=[a-záčďéěíňóřšťúůýž,] )[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+")


def _samples(lines: list[dict]) -> list[str]:
    out = []
    for l in lines:
        line, ctx = l["line"].strip(), (l.get("reply_to") or "").strip().strip("„“\"")
        if not (2 <= len(line) <= 120) or NAME.search(line):
            continue
        if ctx and len(ctx) <= 110 and "vypravěč" not in ctx.lower() and not ctx.lower().startswith("ten druhý") and not NAME.search(ctx):
            out.append(f"Hostitel: {ctx}\nTen druhý: {line}")
        else:
            out.append(f"Ten druhý: {line}")
    step = max(1, len(out) // N_SAMPLES)
    return out[::step][:N_SAMPLES]


@cache
def stable_prefix() -> str:
    """Byte-identical across requests so Gemini's implicit prompt caching can reuse it."""
    parts = [(config.PROMPTS_DIR / "persona.md").read_text().strip()]

    dialogue = config.DERIVED_DIR / "dialogue.jsonl"
    if dialogue.exists():
        sample = _samples([json.loads(l) for l in dialogue.open()])
        parts.append("## Skutečné repliky z knih (jen tón, rytmus a délka – obsah neopakuj)\n\n" + "\n\n".join(sample))

    lore = config.DERIVED_DIR / "lore_bible.md"
    if lore.exists():
        parts.append("## Lore bible (tvoje paměť – používej jen když na to přijde řeč)\n\n" + lore.read_text().strip())
    return "\n\n".join(parts)


def system_prompt(chunks: list[dict], user_name: str = "") -> str:
    # Per-request tail goes after the stable prefix so implicit caching still hits.
    tail = [f"## Teď\nJe {now_line()}. Víš to, ale nekomentuj čas pořád – jen když se to hodí."]
    if user_name:
        tail.append(f"## Čí jsi hlas\nTeď sedíš v hlavě člověka jménem {user_name}. Jménem ho/ji skoro nikdy neoslovuješ.")
    if chunks:
        excerpts = "\n\n".join(f"[{c['book_title']}]\n{c['text']}" for c in chunks)
        tail.append(f"## Úryvky z knih k aktuální otázce\n\n{excerpts}")
    return "\n\n".join([stable_prefix(), *tail])
