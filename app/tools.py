"""Tools he can use, picked by the router (JSON mode) and executed by the app.

Native Gemini function calling (like Search grounding) returns 429 on the free tier, so the per-message router
call — which runs anyway — also returns the actions to take. The app executes them and hands the results to the
reply model, which confirms in his voice.

A tool = name, a one-line spec for the router prompt, a handler(user, args) -> result text, and who may use it.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    spec: str  # shown to the router: what it does + args
    run: Callable[[str, dict], str]
    allowed: Callable[[str], bool] = lambda user: True
    context: Callable[[str], str] | None = None  # extra state for the router (e.g. open reminders, for cancel)


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool):
    REGISTRY[tool.name] = tool


def available(user: str) -> list[Tool]:
    return [t for t in REGISTRY.values() if t.allowed(user)]


def router_block(user: str) -> str:
    tools = available(user)
    if not tools:
        return ""
    specs = "\n".join(f"- {t.name}: {t.spec}" for t in tools)
    ctx = "\n".join(c for t in tools if t.context and (c := t.context(user)))
    return ("NÁSTROJE (actions): použij jen když o to uživatel výslovně žádá nebo to jasně vyplývá ze zprávy:\n"
            + specs + (f"\n\nStav:\n{ctx}" if ctx else ""))


def run(user: str, actions: list[dict]) -> list[str]:
    """Execute router-chosen actions; every result (or error) becomes a line for the reply model."""
    out = []
    for a in actions or []:
        tool = REGISTRY.get(str(a.get("tool")))
        if not tool or not tool.allowed(user):
            continue
        args = {k: v for k, v in a.items() if k != "tool"}
        try:
            out.append(f"{tool.name}: {tool.run(user, args)}")
        except Exception as e:
            out.append(f"{tool.name}: CHYBA – {str(e)[:200]}")
        print(f"  [tool] {user} {tool.name} {args} -> {out[-1][:120]}", flush=True)
    return out
