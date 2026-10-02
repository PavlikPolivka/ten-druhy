"""Read-only calendar from each user's secret iCal URL (Google Calendar → "Secret address in iCal format").

The URL is a credential: stored per user, never sent back to the browser, only fetched server-side.
"""

import threading
import time
import urllib.request
from datetime import date, datetime, timedelta

from app import memory, sessions, tools
from app.prompt import DAYS, TZ

CACHE_S = 600
_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


def _ensure_column():
    memory._db()
    if "ical_url" not in [r[1] for r in sessions.db().execute("PRAGMA table_info(users)")]:
        sessions.db().execute("ALTER TABLE users ADD COLUMN ical_url TEXT")


def url(user: str) -> str | None:
    _ensure_column()
    rows = sessions._q("SELECT ical_url FROM users WHERE user = ?", (user,))
    return rows[0][0] if rows and rows[0][0] else None


def set_url(user: str, value: str | None):
    _ensure_column()
    if value and not value.startswith("https://"):
        raise ValueError("adresa musí začínat https://")
    sessions._q("INSERT INTO users(user, ical_url) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET ical_url = excluded.ical_url",
                (user, value or None))
    with _lock:
        _cache.pop(user, None)


def _fetch(user: str) -> bytes | None:
    u = url(user)
    if not u:
        return None
    with _lock:
        hit = _cache.get(user)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
    req = urllib.request.Request(u, headers={"User-Agent": "ten-druhy/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read(10_000_000)
    with _lock:
        _cache[user] = (time.time(), data)
    return data


def events(user: str, start: date, end: date) -> list[dict]:
    """Events overlapping [start, end) (dates in Prague), recurring ones expanded, sorted."""
    import icalendar
    import recurring_ical_events

    data = _fetch(user)
    if not data:
        return []
    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s, e = ev.get("DTSTART").dt, (ev.get("DTEND").dt if ev.get("DTEND") else None)
        all_day = not isinstance(s, datetime)
        if not all_day:
            s = (s if s.tzinfo else s.replace(tzinfo=TZ)).astimezone(TZ)
            e = (e if e and e.tzinfo else (e.replace(tzinfo=TZ) if e else None))
            e = e.astimezone(TZ) if e else None
        out.append({"start": s, "end": e, "all_day": all_day, "title": str(ev.get("SUMMARY") or "(bez názvu)"),
                    "where": str(ev.get("LOCATION") or "")})
    return sorted(out, key=lambda x: (x["start"] if not x["all_day"] else datetime.combine(x["start"], datetime.min.time(), TZ)))


def _line(ev: dict) -> str:
    d = ev["start"] if ev["all_day"] else ev["start"].date()
    day = f"{DAYS[d.weekday()]} {d.day}. {d.month}."
    when = "celý den" if ev["all_day"] else f"{ev['start']:%H:%M}" + (f"–{ev['end']:%H:%M}" if ev["end"] else "")
    return f"{day} {when}: {ev['title']}" + (f" ({ev['where']})" if ev["where"] else "")


def summary(user: str, start: date, end: date) -> str:
    return "\n".join(_line(e) for e in events(user, start, end))


def prompt_block(user: str) -> str:
    """Today + tomorrow for the per-request prompt tail (empty without a calendar)."""
    if not url(user):
        return ""
    today = datetime.now(TZ).date()
    try:
        text = summary(user, today, today + timedelta(days=2))
    except Exception as e:
        print(f"  [calendar] {user}: {str(e)[:100]}", flush=True)
        return ""
    return "## Jeho kalendář (dnes a zítra)\n" + (text or "nic naplánovaného")


def status(user: str) -> dict:
    if not url(user):
        return {"connected": False}
    try:
        today = datetime.now(TZ).date()
        return {"connected": True, "next7": len(events(user, today, today + timedelta(days=7)))}
    except Exception as e:
        return {"connected": True, "error": str(e)[:120]}


def _lookup(user: str, args: dict) -> str:
    start = date.fromisoformat(str(args["from"])[:10])
    end = date.fromisoformat(str(args.get("to") or args["from"])[:10]) + timedelta(days=1)
    if (end - start).days > 62:
        end = start + timedelta(days=62)
    return summary(user, start, end) or "v tom období nic"


tools.register(tools.Tool(
    "calendar_lookup",
    'podívat se do jeho kalendáře na jiné dny než dnes/zítra („co mám příští týden“, „kdy mám zubaře“). '
    'Args: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}',
    _lookup, allowed=lambda user: bool(url(user))))
