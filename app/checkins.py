"""Proactive check-ins: he messages first ("Tak co, přežili jsme ten deploy?").

A background thread wakes every few minutes. For users with push enabled and something in memory, at most every
CHECK_EVERY_H hours inside the daytime window, Flash-Lite decides whether a check-in makes sense right now and writes
it. Max one per user per day, and never while the user is actively chatting.

  python -m app.checkins --user pavel [--force]   # evaluate one user now (force: ignore window/cooldowns)
"""

import json
import sys
import threading
import time
from datetime import datetime, timezone

from app import config, llm, memory, push, sessions
from app.prompt import TZ, now_line

CHECK_EVERY_H = 2
ACTIVE_COOLDOWN_H = 3
WINDOW = (9, 21)  # local hours
TICK_S = 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent INTEGER NOT NULL, message TEXT, conversation TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_checkins_user ON checkins(user, ts);
"""

DECIDE_SYSTEM = """Jsi „Ten druhý“ – cynický vnitřní hlas uživatele z knih Jiřího Kulhánka. Mluvíš česky, hovorově, \
krátce (1–2 věty), suše, s černým humorem, ale jde ti o něj. Teď se můžeš SÁM ozvat – jako když se člověku v hlavě \
ozve vnitřní hlas.

Rozhodni, jestli má smysl se ozvat PRÁVĚ TEĎ. Ozvi se jen s dobrým důvodem z paměti: událost, která je dnes / právě \
proběhla / blíží se (deploy, narozeniny, doktor, výlet, zkouška), nebo něco, co nechal viset. Žádné obecné „jak se máš“. \
NIKDY nevymýšlej, jak něco dopadlo – výsledek neznáš, tak se zeptej („Tak co, spadlo to?“). Když nic takového není, neozývej se. Neozývej se kvůli věcem, ke kterým ses už ozval (viz poslední ozvání).

Vrať JSON: {"send": true|false, "reason": "<proč, krátce>", "message": "<zpráva v jeho stylu, pokud send>"}"""

_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        _ready = True
    return sessions._q(sql, args)


def _utc(ts: str) -> datetime:
    """SQLite CURRENT_TIMESTAMP is UTC 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def _hours_since(ts: str | None) -> float:
    return (datetime.now(timezone.utc) - _utc(ts)).total_seconds() / 3600 if ts else 1e9


def _due(user: str) -> str | None:
    """Why NOT to evaluate now (None = go ahead)."""
    now = datetime.now(TZ)
    if not (WINDOW[0] <= now.hour < WINDOW[1]):
        return "outside window"
    last = _q("SELECT ts, sent FROM checkins WHERE user = ? ORDER BY id DESC LIMIT 1", (user,))
    if last and _hours_since(last[0][0]) < CHECK_EVERY_H:
        return "evaluated recently"
    midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if _q("SELECT 1 FROM checkins WHERE user = ? AND sent = 1 AND ts >= ?", (user, midnight_utc.strftime("%Y-%m-%d %H:%M:%S"))):
        return "already checked in today"
    active = _q("SELECT MAX(m.ts) FROM messages m JOIN conversations c ON c.id = m.conversation"
                " WHERE c.user = ? AND m.role = 'user'", (user,))
    if active and _hours_since(active[0][0]) < ACTIVE_COOLDOWN_H:
        return "user active recently"
    if not memory.visible(user):
        return "nothing in memory"
    return None


def evaluate(user: str, force: bool = False) -> dict:
    if not force:
        why = _due(user)
        if why:
            return {"send": False, "reason": why, "skipped": True}
    facts = "\n".join(f"- {f['text']}" for f in reversed(memory.visible(user))) or "(nic)"
    recent = _q("SELECT ts, message FROM checkins WHERE user = ? AND sent = 1 ORDER BY id DESC LIMIT 5", (user,))
    recent_txt = "\n".join(f"- {ts} UTC: {m}" for ts, m in recent) or "(zatím nikdy)"
    titles = "\n".join(f"- {c['title'] or c['preview']} ({c['updated']} UTC)" for c in sessions.conversations(user, 5)) or "(nic)"
    user_msg = (f"Teď je: {now_line()}\n\nCo o něm víš:\n{facts}\n\nPoslední konverzace:\n{titles}\n\n"
                f"Poslední tvoje ozvání:\n{recent_txt}")
    from app.prompt import TONE_RULES
    system = DECIDE_SYSTEM + ("\n\n" + TONE_RULES[memory.tone(user)[0]] if memory.tone(user)[0] in TONE_RULES else "")
    out = json.loads(llm.generate(system, user_msg, json_mode=True, temperature=0.7, patient=False))
    send, msg, reason = bool(out.get("send")), (out.get("message") or "").strip(), (out.get("reason") or "")[:200]
    cid = None
    if send and msg:
        cid = sessions.create(user)
        sessions.add(cid, "assistant", msg)
        sessions.set_title(cid, "Ozval se sám")
        push.send(user, "Ten druhý", msg, f"/?c={cid}")
    _q("INSERT INTO checkins(user, sent, message, conversation, reason) VALUES (?, ?, ?, ?, ?)",
       (user, int(bool(cid)), msg if cid else None, cid, reason))
    return {"send": bool(cid), "reason": reason, "message": msg, "conversation": cid}


def _loop():
    time.sleep(60)  # let the app start
    while True:
        try:
            memory.sweep()
        except Exception as e:
            print(f"  [memory] sweep: {str(e)[:100]}", flush=True)
        for user in push.users():
            try:
                r = evaluate(user)
                if not r.get("skipped"):
                    print(f"  [checkin] {user}: send={r['send']} ({r['reason']})", flush=True)
            except Exception as e:  # quota, bad JSON: try again next tick
                print(f"  [checkin] {user}: {str(e)[:100]}", flush=True)
        time.sleep(TICK_S)


def start():
    # The loop also sweeps memory extraction, so it runs even if push check-ins are unused.
    if config.CHECKINS:
        threading.Thread(target=_loop, daemon=True, name="checkins").start()


if __name__ == "__main__":
    args = sys.argv[1:]
    who = args[args.index("--user") + 1] if "--user" in args else "local"
    print(evaluate(who, force="--force" in args))
