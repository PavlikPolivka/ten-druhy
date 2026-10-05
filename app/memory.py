"""Memory 2.0 (design: docs/MEMORY.md).

Day: every exchange → Flash-Lite writes raw observations into the episodic log (aggressive, no dedupe).
Night: the dream (app/dream.py) consolidates episodes into facts, forgets, links, rewrites the core profile.
Prompt: core profile + most relevant facts + facts dated soon + raw episodes of the last 48 h.

Facts live in the `memories` table (kept for compatibility, extended with Memory 2.0 columns).
Scope "family" facts are visible to users who opted in to family sharing.
"""

import json
import math
import struct
import threading

from app import config, llm, sessions, tools
from app.prompt import now_line

RELEVANT_K = 15
ALL_IF_UNDER = 40  # with few facts, just include them all
EPISODE_HOURS = 48
MAX_EPISODES_IN_PROMPT = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'user', text TEXT NOT NULL,
    conversation TEXT, created DATETIME DEFAULT CURRENT_TIMESTAMP, updated DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_mem_user ON memories(user, updated);
CREATE TABLE IF NOT EXISTS users (user TEXT PRIMARY KEY, share_family INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS memory_progress (conversation TEXT PRIMARY KEY, upto INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP, conversation TEXT,
    text TEXT NOT NULL, emotion TEXT, about TEXT, dream_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_ep_user ON episodes(user, ts);
CREATE TABLE IF NOT EXISTS profile (user TEXT PRIMARY KEY, text TEXT NOT NULL, updated DATETIME DEFAULT CURRENT_TIMESTAMP);
"""
# Memory 2.0 columns added to the old `memories` table (existing rows become plain facts).
FACT_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'fact'",          # fact | inference | event | preference | routine | goal | self
    "category": "TEXT NOT NULL DEFAULT 'ostatní'",
    "confidence": "REAL NOT NULL DEFAULT 0.7",
    "evidence": "INTEGER NOT NULL DEFAULT 1",
    "importance": "INTEGER NOT NULL DEFAULT 3",      # 1..5
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'active'",      # active | archived
    "last_seen": "DATETIME",
    "valid_until": "TEXT",                            # ISO date for events/plans
    "sources": "TEXT NOT NULL DEFAULT '[]'",          # conversation ids
    "entities": "TEXT NOT NULL DEFAULT '[]'",
    "embedding": "BLOB",
}
CATEGORIES = ["rodina", "vztahy", "práce", "zdraví", "peníze", "domov", "koníčky", "zvyky", "preference", "plány",
              "cíle", "nálady", "ten druhý", "ostatní"]

CAPTURE_SYSTEM = """Jsi paměť postavy „Ten druhý“ – vnitřního hlasu uživatele. Z poslední výměny zapiš VŠECHNO, co se \
o uživateli dá vypozorovat – i drobnosti: co dělá, co plánuje (s absolutním datem), co ho štve nebo těší, názory, \
preference, lidé a vztahy, práce, zdraví, peníze, zvyky, nálada, vtipy, na které reagoval. Klidně i věci, které už \
víš – zítra se to v noci roztřídí, duplicity nevadí.
Dostaneš jen slova uživatele; odpověď Toho druhého je jen kontext (jeho vtipy a návrhy NEJSOU fakta o uživateli).
Relativní data převeď na absolutní podle aktuálního data. Piš česky, krátce, ve 3. osobě („Štve ho šéf.“).
Když výměna nic neříká (pozdrav, „jo“, test), vrať prázdný seznam.
Vrať JSON: {"observations": [{"text": "...", "emotion": "<jedno slovo nebo prázdné>", "about": "<koho/čeho se to týká>"}]}"""

_running: set[str] = set()
_lock = threading.Lock()
_ready = False


def _db():
    global _ready
    db = sessions.db()
    if not _ready:
        db.executescript(SCHEMA)
        cols = [r[1] for r in db.execute("PRAGMA table_info(memories)")]
        for col, ddl in FACT_COLUMNS.items():
            if col not in cols:
                db.execute(f"ALTER TABLE memories ADD COLUMN {col} {ddl}")
        db.execute("UPDATE memories SET last_seen = updated WHERE last_seen IS NULL")
        db.commit()
        _ready = True
    return db


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    _db()
    return sessions._q(sql, args)


# ---- per-user settings (tone, family sharing) ----

TONES = ("full", "mild", "kid")


def _ensure_tone_column():
    if "tone" not in [r[1] for r in sessions.db().execute("PRAGMA table_info(users)")]:
        sessions.db().execute("ALTER TABLE users ADD COLUMN tone TEXT NOT NULL DEFAULT 'full'")


def tone(user: str) -> tuple[str, bool]:
    """(tone, locked). A lock from TONE_LOCK in .env wins over the user's own choice."""
    if user in config.TONE_LOCK:
        return config.TONE_LOCK[user], True
    _db(); _ensure_tone_column()
    rows = _q("SELECT tone FROM users WHERE user = ?", (user,))
    return (rows[0][0] if rows and rows[0][0] in TONES else "full"), False


def set_tone(user: str, value: str) -> bool:
    if value not in TONES or user in config.TONE_LOCK:
        return False
    _db(); _ensure_tone_column()
    _q("INSERT INTO users(user, tone) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET tone = excluded.tone", (user, value))
    return True


def shares_family(user: str) -> bool:
    rows = _q("SELECT share_family FROM users WHERE user = ?", (user,))
    return bool(rows and rows[0][0])


def set_share_family(user: str, on: bool):
    _q("INSERT INTO users(user, share_family) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET share_family = excluded.share_family",
       (user, int(on)))


# ---- facts ----

FACT_FIELDS = ("id", "user", "scope", "text", "kind", "category", "confidence", "evidence", "importance", "pinned",
               "status", "created", "updated", "last_seen", "valid_until", "sources", "entities")


def _row(r) -> dict:
    d = dict(zip(FACT_FIELDS, r))
    d["sources"] = json.loads(d["sources"] or "[]")
    d["entities"] = json.loads(d["entities"] or "[]")
    return d


def facts(user: str, status: str = "active", include_family: bool = True) -> list[dict]:
    """The user's own facts (+ family facts from opted-in users if this user opted in too)."""
    cols = ", ".join(f"m.{c}" for c in FACT_FIELDS)
    if include_family and shares_family(user):
        rows = _q(f"""SELECT {cols} FROM memories m LEFT JOIN users u ON u.user = m.user
                      WHERE m.status = ? AND (m.user = ? OR (m.scope = 'family' AND u.share_family = 1))
                      ORDER BY m.importance DESC, m.last_seen DESC""", (status, user))
    else:
        rows = _q(f"SELECT {cols} FROM memories m WHERE m.status = ? AND m.user = ? "
                  "ORDER BY m.importance DESC, m.last_seen DESC", (status, user))
    out = [_row(r) for r in rows]
    for f in out:
        f["own"] = f["user"] == user
    return out


def visible(user: str) -> list[dict]:
    """Back-compat: active facts (own + shared family)."""
    return facts(user)


def get(fact_id: int) -> dict | None:
    rows = _q(f"SELECT {', '.join(FACT_FIELDS)} FROM memories WHERE id = ?", (fact_id,))
    return _row(rows[0]) if rows else None


def add_fact(user: str, text: str, **kw) -> int:
    _db()
    with sessions._lock:
        cur = sessions.db().execute(
            "INSERT INTO memories(user, scope, text, conversation, kind, category, confidence, evidence, importance, pinned,"
            " last_seen, valid_until, sources, entities) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
            (user, kw.get("scope", "user"), text.strip(), kw.get("conversation"), kw.get("kind", "fact"),
             kw.get("category", "ostatní"), float(kw.get("confidence", 0.7)), int(kw.get("evidence", 1)),
             int(kw.get("importance", 3)), int(bool(kw.get("pinned"))), kw.get("valid_until"),
             json.dumps(kw.get("sources", []), ensure_ascii=False), json.dumps(kw.get("entities", []), ensure_ascii=False)))
        sessions.db().commit()
        return cur.lastrowid


def update_fact(fact_id: int, **kw):
    allowed = {"text", "kind", "category", "confidence", "evidence", "importance", "pinned", "status", "valid_until",
               "scope", "sources", "entities"}
    sets, args = [], []
    for k, v in kw.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            args.append(json.dumps(v, ensure_ascii=False) if k in ("sources", "entities") else v)
    if "text" in kw:
        sets.append("embedding = NULL")  # re-embedded lazily
    if not sets:
        return
    _q(f"UPDATE memories SET {', '.join(sets)}, updated = CURRENT_TIMESTAMP, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
       (*args, fact_id))


def delete(user: str, memory_id: int) -> bool:
    if not _q("SELECT 1 FROM memories WHERE id = ? AND user = ?", (memory_id, user)):
        return False
    _q("DELETE FROM memories WHERE id = ?", (memory_id,))
    return True


# ---- embeddings for relevance (cheap: facts are short and embedded once) ----

def _pack(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def _unpack(b: bytes) -> list[float]:
    return list(struct.unpack(f"{len(b) // 4}f", b))


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def embed_missing(user: str, limit: int = 100):
    rows = _q("SELECT id, text FROM memories WHERE user = ? AND status = 'active' AND embedding IS NULL LIMIT ?", (user, limit))
    for i in range(0, len(rows), 20):
        batch = rows[i:i + 20]
        try:
            vecs = llm.embed([t for _, t in batch], retry=False)
        except Exception as e:
            print(f"  [memory] embed facts: {str(e)[:80]}", flush=True)
            return
        for (fid, _), v in zip(batch, vecs):
            _q("UPDATE memories SET embedding = ? WHERE id = ?", (_pack(v), fid))


def relevant(user: str, message: str, k: int = RELEVANT_K) -> list[dict]:
    """Most relevant active facts for a message: embedding similarity + keyword overlap + importance."""
    fs = facts(user)
    if len(fs) <= ALL_IF_UNDER or not message.strip():
        return fs
    embs = {i: _unpack(b) for i, b in _q("SELECT id, embedding FROM memories WHERE embedding IS NOT NULL AND user = ?", (user,))}
    try:
        qv = llm.embed([message], query=True, retry=False)[0] if embs else None
    except Exception:
        qv = None
    from app.textnorm import tokens
    qt = set(tokens(message))

    def score(f):
        s = 0.15 * f["importance"] + (1.0 if f["pinned"] else 0.0)
        if qv is not None and f["id"] in embs:
            s += 3.0 * _cos(qv, embs[f["id"]])
        overlap = qt & set(tokens(f["text"] + " " + " ".join(f["entities"])))
        s += 0.6 * len(overlap)
        return s

    return sorted(fs, key=score, reverse=True)[:k]


def upcoming(user: str, days: int = 7) -> list[dict]:
    rows = _q(f"SELECT {', '.join(FACT_FIELDS)} FROM memories WHERE user = ? AND status = 'active' AND valid_until IS NOT NULL "
              "AND valid_until >= date('now') AND valid_until <= date('now', ?) ORDER BY valid_until", (user, f"+{days} days"))
    return [_row(r) for r in rows]


def recent_episodes(user: str, hours: int = EPISODE_HOURS, limit: int = MAX_EPISODES_IN_PROMPT) -> list[dict]:
    # Only not-yet-dreamt ones: after the dream they live on as facts.
    rows = _q("SELECT id, ts, text, emotion FROM episodes WHERE user = ? AND dream_id IS NULL AND ts >= datetime('now', ?) "
              "ORDER BY id DESC LIMIT ?", (user, f"-{hours} hours", limit))
    return [{"id": i, "ts": t, "text": x, "emotion": e} for i, t, x, e in reversed(rows)]


def profile(user: str) -> dict | None:
    rows = _q("SELECT text, updated FROM profile WHERE user = ?", (user,))
    return {"text": rows[0][0], "updated": rows[0][1]} if rows else None


def set_profile(user: str, text: str):
    _q("INSERT INTO profile(user, text) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET text = excluded.text, "
       "updated = CURRENT_TIMESTAMP", (user, text.strip()))


def prompt_block(user: str, message: str = "") -> str:
    parts = []
    p = profile(user)
    if p:
        parts.append("Kdo to je (tvoje jádro paměti):\n" + p["text"])
    seen = set()
    rel = relevant(user, message)
    if rel:
        lines = []
        for f in rel:
            seen.add(f["id"])
            tag = " (odhad, nejisté)" if f["kind"] == "inference" else ""
            src = "" if f["own"] else f" (ví to od: {f['user']})"
            lines.append(f"- {f['text']}{tag}{src}")
        parts.append("Co o něm víš:\n" + "\n".join(lines))
    up = [f for f in upcoming(user) if f["id"] not in seen]
    if up:
        parts.append("Blíží se:\n" + "\n".join(f"- {f['valid_until']}: {f['text']}" for f in up))
    eps = recent_episodes(user)
    if eps:
        parts.append("Čerstvé postřehy z posledních dní (ještě neutříděné):\n" + "\n".join(f"- {e['text']}" for e in eps))
    from app import dream
    qs = dream.open_items(user, "question")
    if qs:
        parts.append("Něco, co si chceš časem nenásilně ujasnit (jen když se to hodí, max jednou):\n- " + qs[0]["text"])
    last = dream.last_dream(user)
    if last and last.get("dream_text"):
        parts.append(f"Tvůj poslední sen (z noci {last['ts'][:10]}; vyprávěj ho, jen když se zeptá nebo se to hodí):\n"
                     + last["dream_text"])
    st = dream.style(user)
    if st:
        parts.append("Jak s ním mluvit (z jeho hodnocení tvých odpovědí):\n" + st)
    if not parts:
        return ""
    return ("## Tvoje paměť o něm\nBer to jako samozřejmost, co prostě víš. Vytáhni to, když se to hodí – nikdy to "
            "nevyjmenovávej a nepřiznávej, že máš „paměť“.\n\n" + "\n\n".join(parts))


# ---- day: aggressive capture into the episodic log ----

def capture(user: str, conversation: str):
    """Every new exchange → observations (episodes). Uses memory_progress to process each message once."""
    rows = _q("SELECT upto FROM memory_progress WHERE conversation = ?", (conversation,))
    upto = rows[0][0] if rows else 0
    new = [m for m in sessions.messages(conversation) if m["id"] > upto]
    said = [m for m in new if m["role"] == "user" and m["content"].strip()]
    if not said:
        if new:
            _set_progress(conversation, new[-1]["id"])
        return
    convo = "\n".join(f"{'Uživatel' if m['role'] == 'user' else 'Ten druhý (jen kontext)'}: {m['content']}" for m in new)
    out = json.loads(llm.generate(CAPTURE_SYSTEM, f"Aktuální datum: {now_line()}\n\n{convo}", json_mode=True,
                                  temperature=0, patient=False))
    for o in out.get("observations") or []:
        text = (o.get("text") or "").strip()
        if text:
            _q("INSERT INTO episodes(user, conversation, text, emotion, about) VALUES (?, ?, ?, ?, ?)",
               (user, conversation, text, (o.get("emotion") or "")[:40], (o.get("about") or "")[:80]))
    _set_progress(conversation, new[-1]["id"])


def _set_progress(conversation: str, upto: int):
    _q("INSERT INTO memory_progress(conversation, upto) VALUES (?, ?) ON CONFLICT(conversation) DO UPDATE SET upto = excluded.upto",
       (conversation, upto))


def extract_async(user: str, conversation: str):
    """Fire-and-forget after every reply; one capture per conversation at a time."""
    with _lock:
        if conversation in _running:
            return
        _running.add(conversation)

    def run():
        try:
            capture(user, conversation)
        except Exception as e:  # quota / bad JSON: the idle sweep retries
            print(f"  [memory] capture skipped: {str(e)[:100]}", flush=True)
        finally:
            with _lock:
                _running.discard(conversation)

    threading.Thread(target=run, daemon=True).start()


def sweep(idle_minutes: int = 10):
    """Capture anything missed (quota failures) in conversations idle for a while."""
    rows = _q("""SELECT c.id, c.user FROM conversations c
                 WHERE c.updated <= datetime('now', ?)
                 AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation = c.id AND m.role = 'user'
                             AND m.id > COALESCE((SELECT upto FROM memory_progress p WHERE p.conversation = c.id), 0))""",
              (f"-{idle_minutes} minutes",))
    for cid, user in rows:
        try:
            capture(user, cid)
        except Exception as e:
            print(f"  [memory] sweep {cid[:8]}: {str(e)[:80]}", flush=True)


# ---- the 🧠 note under a reply: what was just noticed ----

def max_id() -> int:
    rows = _q("SELECT COALESCE(MAX(id), 0) FROM episodes")
    return rows[0][0]


def changed_since(user: str, conversation: str, after_id: int) -> list[dict]:
    rows = _q("SELECT id, text FROM episodes WHERE user = ? AND conversation = ? AND id > ? ORDER BY id",
              (user, conversation, after_id))
    return [{"id": i, "text": t} for i, t in rows]


# ---- tools: "pamatuj si…" / "zapomeň na…" ----

def _remember(user: str, args: dict) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("co si mám zapamatovat?")
    fid = add_fact(user, text, importance=5, pinned=True, confidence=1.0,
                   category=args.get("category") if args.get("category") in CATEGORIES else "ostatní")
    return f"zapamatováno natrvalo [{fid}]: „{text}“"


def _forget(user: str, args: dict) -> str:
    """Forget facts and episodes matching a description (keyword + embedding)."""
    what = str(args.get("what") or "").strip()
    if not what:
        raise ValueError("na co mám zapomenout?")
    from app.textnorm import tokens
    qt = set(tokens(what))
    hits = []
    for f in facts(user, include_family=False) + facts(user, status="archived", include_family=False):
        overlap = len(qt & set(tokens(f["text"])))
        if qt and overlap >= max(1, min(2, len(qt))):
            hits.append(f)
    for f in hits:
        _q("DELETE FROM memories WHERE id = ?", (f["id"],))
    n_ep = 0
    for eid, text in _q("SELECT id, text FROM episodes WHERE user = ?", (user,)):
        if qt and len(qt & set(tokens(text))) >= max(1, min(2, len(qt))):
            _q("DELETE FROM episodes WHERE id = ?", (eid,))
            n_ep += 1
    if not hits and not n_ep:
        return f"nic odpovídajícího „{what}“ jsem v paměti nenašel"
    return f"zapomenuto {len(hits)} faktů ({'; '.join(f['text'] for f in hits[:5])}) a {n_ep} postřehů"


tools.register(tools.Tool("memory_remember", 'zapamatovat si něco natrvalo, když o to výslovně žádá („pamatuj si, že…“). '
                                             'Args: {"text": "fakt ve 3. osobě", "category": "jedna z: ' + ", ".join(CATEGORIES) + '"}',
                          _remember))
tools.register(tools.Tool("memory_forget", 'zapomenout něco, když o to výslovně žádá („zapomeň na…“, „tohle si nepamatuj“). '
                                           'Args: {"what": "o čem to je, pár klíčových slov"}', _forget))
