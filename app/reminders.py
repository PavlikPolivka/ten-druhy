"""Reminders: created from chat via the router, fired by a background thread as a push + a new conversation."""

import threading
import time
from datetime import datetime, timezone

from app import llm, push, sessions, tools
from app.prompt import DAYS, MONTHS, TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, due TEXT NOT NULL, text TEXT NOT NULL,
    created DATETIME DEFAULT CURRENT_TIMESTAMP, fired INTEGER NOT NULL DEFAULT 0, cancelled INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_rem_due ON reminders(fired, cancelled, due);
"""
TICK_S = 20
_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        _ready = True
    return sessions._q(sql, args)


def _human(dt: datetime) -> str:
    dt = dt.astimezone(TZ)
    return f"{DAYS[dt.weekday()]} {dt.day}. {MONTHS[dt.month - 1]} v {dt:%H:%M}"


def _parse(when: str) -> datetime:
    dt = datetime.fromisoformat(str(when).strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt  # the router gives local Prague time


def create(user: str, args: dict) -> str:
    due, text = _parse(args["when"]), str(args.get("text") or "").strip()
    if not text:
        raise ValueError("chybí text připomínky")
    if due <= datetime.now(TZ):
        raise ValueError(f"čas {_human(due)} už je v minulosti")
    _q("INSERT INTO reminders(user, due, text) VALUES (?, ?, ?)", (user, due.astimezone(timezone.utc).isoformat(), text))
    return f"vytvořeno – {_human(due)}: „{text}“"


def open_reminders(user: str) -> list[dict]:
    rows = _q("SELECT id, due, text FROM reminders WHERE user = ? AND fired = 0 AND cancelled = 0 ORDER BY due", (user,))
    return [{"id": i, "due": d, "when": _human(datetime.fromisoformat(d)), "text": t} for i, d, t in rows]


def list_(user: str, args: dict) -> str:
    items = open_reminders(user)
    return "; ".join(f"[{r['id']}] {r['when']}: {r['text']}" for r in items) or "žádné nejsou"


def cancel(user: str, args: dict) -> str:
    rid = int(args["id"])
    row = _q("SELECT due, text FROM reminders WHERE id = ? AND user = ? AND fired = 0 AND cancelled = 0", (rid, user))
    if not row:
        raise ValueError(f"připomínka {rid} neexistuje")
    _q("UPDATE reminders SET cancelled = 1 WHERE id = ?", (rid,))
    # Full details, or the reply model guesses them ("tu dnešní v pět").
    return f"zrušeno – {_human(datetime.fromisoformat(row[0][0]))}: „{row[0][1]}“"


def _context(user: str) -> str:
    items = open_reminders(user)
    return "Otevřené připomínky: " + ("; ".join(f"[{r['id']}] {r['when']}: {r['text']}" for r in items) if items else "žádné")


tools.register(tools.Tool("reminder_create",
                          'připomenout něco v daný čas. Args: {"when": "YYYY-MM-DDTHH:MM" (místní čas Praha, dopočítej '
                          'z aktuálního data: „zítra v 8“, „za 2 hodiny“, „v pondělí ráno“ = 8:00), "text": "co připomenout"}',
                          create))
tools.register(tools.Tool("reminder_list", "vypsat jeho otevřené připomínky. Args: {}", list_))
tools.register(tools.Tool("reminder_cancel", 'zrušit připomínku. Args: {"id": číslo ze stavu}', cancel, context=_context))

FIRE_SYSTEM = ("Jsi Ten druhý, cynický vnitřní hlas. Připomeň mu tuhle věc – česky, hovorově, 1 krátká věta, suše, "
               "obsah připomínky musí jasně zaznít. Vrať jen tu větu.")


def _fire(rid: int, user: str, text: str):
    try:
        msg = llm.generate(FIRE_SYSTEM, f"Připomínka: {text}", temperature=0.8, patient=False).strip() or f"Připomínám: {text}"
    except Exception:
        msg = f"Připomínám: {text}"
    cid = sessions.create(user)
    sessions.add(cid, "assistant", msg)
    sessions.set_title(cid, f"Připomínka: {text}"[:60])
    push.send(user, "Ten druhý – připomínka", msg, f"/?c={cid}")
    print(f"  [reminder] fired {rid} for {user}", flush=True)


def _loop():
    while True:
        try:
            due = _q("SELECT id, user, text FROM reminders WHERE fired = 0 AND cancelled = 0 AND due <= ?",
                     (datetime.now(timezone.utc).isoformat(),))
            for rid, user, text in due:
                _q("UPDATE reminders SET fired = 1 WHERE id = ?", (rid,))  # mark first: never double-fire
                _fire(rid, user, text)
        except Exception as e:
            print(f"  [reminder] {str(e)[:100]}", flush=True)
        time.sleep(TICK_S)


def start():
    threading.Thread(target=_loop, daemon=True, name="reminders").start()
