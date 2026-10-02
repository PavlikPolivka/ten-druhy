"""Opt-in rituals: an evening journal question and a Sunday weekly review, in his voice.

Run from the scheduler loop (app/checkins.py). Each lands as a new conversation started by him (+ push if the user
has it), at most once per day / week (sent log).

  python -m app.rituals journal|weekly|brief --user pavel   # force one now (testing)
"""

import json
import sys
from datetime import datetime, timedelta, timezone

from app import calendar_ics, llm, memory, push, sessions, web
from app.prompt import DAYS, MONTHS, TZ, now_line

JOURNAL_AT = (20, 30)
BRIEF_AT = {0: (7, 0), 1: (7, 0), 2: (7, 0), 3: (7, 0), 4: (7, 0), 5: (9, 0), 6: (9, 0)}  # weekday -> (h, m)
WEEKLY_AT = (6, 18, 30)  # Sunday 18:30
QUIET_AFTER_ACTIVITY_H = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS rituals_sent (user TEXT NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user, kind, period));
"""
VOICE = ("Jsi „Ten druhý“ – cynický vnitřní hlas uživatele z knih Jiřího Kulhánka. Česky, hovorově, suše, s černým "
         "humorem, ale jde ti o něj. Nikdy si nevymýšlej fakta, která nejsou v podkladech.")
JOURNAL_SYSTEM = VOICE + (" Je večer a ty se ho ptáš, jak proběhl den – jako vnitřní hlas, co to chce vědět. "
                          "1–2 krátké věty. Když dnes měl něco konkrétního (kalendář, paměť), zeptej se na to.")
BRIEF_SYSTEM = VOICE + (" Je ráno a ty mu dáváš ranní přehled: co ho dnes čeká (kalendář, věci z paměti s dnešním datem) "
                        "a jaké bude počasí, s praktickým dopadem (bunda, deštník, kolo). 2–4 krátké věty, konkrétní časy. "
                        "Když nic naplánovaného nemá, řekni to po svém.")
WEEKLY_SYSTEM = VOICE + (" Je neděle večer: shrň mu jeho týden (4–6 vět, co se dělo, co zvládl, co visí) a jednou větou "
                         "se podívej na příští týden. Vlastní slova, žádné odrážky, žádné nadpisy.")

_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        memory._db()
        cols = [r[1] for r in sessions.db().execute("PRAGMA table_info(users)")]
        for col in ("journal", "weekly", "brief"):
            if col not in cols:
                sessions.db().execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
        _ready = True
    return sessions._q(sql, args)


def settings(user: str) -> dict:
    rows = _q("SELECT journal, weekly, brief FROM users WHERE user = ?", (user,))
    return {"journal": bool(rows and rows[0][0]), "weekly": bool(rows and rows[0][1]), "brief": bool(rows and rows[0][2])}


def set_setting(user: str, kind: str, on: bool):
    assert kind in ("journal", "weekly", "brief")
    _q(f"INSERT INTO users(user, {kind}) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET {kind} = excluded.{kind}",
       (user, int(on)))


def _users(kind: str) -> list[str]:
    return [u for (u,) in _q(f"SELECT user FROM users WHERE {kind} = 1")]


def _deliver(user: str, kind: str, period: str, title: str, text: str) -> str:
    cid = sessions.create(user)
    sessions.add(cid, "assistant", text)
    sessions.set_title(cid, title)
    _q("INSERT OR IGNORE INTO rituals_sent(user, kind, period) VALUES (?, ?, ?)", (user, kind, period))
    push.send(user, "Ten druhý", text, f"/?c={cid}")
    return cid


def _facts(user: str) -> str:
    return "\n".join(f"- {f['text']}" for f in reversed(memory.visible(user))) or "(nic)"


def journal(user: str) -> str:
    now = datetime.now(TZ)
    today = now.date()
    try:
        cal = calendar_ics.summary(user, today, today + timedelta(days=1)) if calendar_ics.url(user) else ""
    except Exception:
        cal = ""
    ctx = f"Teď je: {now_line()}\n\nDnešní kalendář:\n{cal or '(nic / nepropojený)'}\n\nCo o něm víš:\n{_facts(user)}"
    text = llm.generate(JOURNAL_SYSTEM, ctx, temperature=0.9, patient=False).strip() or "Tak co dneska? Přežili jsme?"
    title = f"Deník – {DAYS[today.weekday()]} {today.day}. {today.month}."
    return _deliver(user, "journal", today.isoformat(), title, text)


def brief(user: str) -> str:
    today = datetime.now(TZ).date()
    try:
        cal = calendar_ics.summary(user, today, today + timedelta(days=1)) if calendar_ics.url(user) else ""
    except Exception:
        cal = ""
    try:
        weather = web.weather()
    except Exception:
        weather = "(počasí se nepodařilo načíst)"
    ctx = (f"Teď je: {now_line()}\n\nDnešní kalendář:\n{cal or '(nic / nepropojený)'}\n\n"
           f"Co o něm víš (hledej, co je na dnešek):\n{_facts(user)}\n\nPočasí:\n{weather}")
    text = llm.generate(BRIEF_SYSTEM, ctx, temperature=0.8, patient=False).strip()
    if not text:
        raise RuntimeError("empty brief")
    return _deliver(user, "brief", today.isoformat(), f"Ráno – {DAYS[today.weekday()]} {today.day}. {today.month}.", text)


def weekly(user: str) -> str:
    now = datetime.now(TZ)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    since = datetime.combine(week_start, datetime.min.time(), TZ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new = _q("SELECT text FROM memories WHERE user = ? AND updated >= ? ORDER BY updated", (user, since))
    titles = [c["title"] or c["preview"] for c in sessions.conversations(user, 40) if c["updated"] >= since]
    try:
        nxt = calendar_ics.summary(user, today + timedelta(days=1), today + timedelta(days=8)) if calendar_ics.url(user) else ""
    except Exception:
        nxt = ""
    ctx = (f"Teď je: {now_line()}\n\nCo jsi se o něm tenhle týden dozvěděl:\n"
           + ("\n".join(f"- {t}" for (t,) in new) or "(nic nového)")
           + "\n\nO čem jste se bavili (názvy konverzací):\n" + ("\n".join(f"- {t}" for t in titles) or "(nic)")
           + f"\n\nPříští týden v kalendáři:\n{nxt or '(nic / nepropojený)'}")
    text = llm.generate(WEEKLY_SYSTEM, ctx, temperature=0.8, patient=False).strip()
    if not text:
        raise RuntimeError("empty weekly review")
    title = f"Týden v kostce – {week_start.day}. {MONTHS[week_start.month - 1]}"
    return _deliver(user, "weekly", week_start.isoformat(), title, text)


def _active_recently(user: str) -> bool:
    rows = _q("SELECT MAX(m.ts) FROM messages m JOIN conversations c ON c.id = m.conversation"
              " WHERE c.user = ? AND m.role = 'user'", (user,))
    if not rows or not rows[0][0]:
        return False
    last = datetime.fromisoformat(rows[0][0]).replace(tzinfo=timezone.utc)  # SQLite timestamps are UTC
    return datetime.now(timezone.utc) - last < timedelta(hours=QUIET_AFTER_ACTIVITY_H)


def tick():
    """Called every scheduler tick; sends what's due."""
    now = datetime.now(TZ)
    if (now.hour, now.minute) >= BRIEF_AT[now.weekday()] and now.hour < 12:
        for user in _users("brief"):
            if not _q("SELECT 1 FROM rituals_sent WHERE user = ? AND kind = 'brief' AND period = ?",
                      (user, now.date().isoformat())):
                try:
                    brief(user)
                    print(f"  [ritual] brief -> {user}", flush=True)
                except Exception as e:
                    print(f"  [ritual] brief {user}: {str(e)[:100]}", flush=True)
    if (now.hour, now.minute) >= JOURNAL_AT and now.hour < 23:
        for user in _users("journal"):
            if not _q("SELECT 1 FROM rituals_sent WHERE user = ? AND kind = 'journal' AND period = ?",
                      (user, now.date().isoformat())) and not _active_recently(user):
                try:
                    journal(user)
                    print(f"  [ritual] journal -> {user}", flush=True)
                except Exception as e:
                    print(f"  [ritual] journal {user}: {str(e)[:100]}", flush=True)
    wd, h, m = WEEKLY_AT
    if now.weekday() == wd and (now.hour, now.minute) >= (h, m) and now.hour < 23:
        week = (now.date() - timedelta(days=now.weekday())).isoformat()
        for user in _users("weekly"):
            if not _q("SELECT 1 FROM rituals_sent WHERE user = ? AND kind = 'weekly' AND period = ?", (user, week)):
                try:
                    weekly(user)
                    print(f"  [ritual] weekly -> {user}", flush=True)
                except Exception as e:
                    print(f"  [ritual] weekly {user}: {str(e)[:100]}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    who = args[args.index("--user") + 1] if "--user" in args else "local"
    cid = {"journal": journal, "brief": brief}.get(args[0] if args else "", weekly)(who)
    print(json.dumps(sessions.messages(cid), ensure_ascii=False, indent=1))
