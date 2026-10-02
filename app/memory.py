"""Long-term memory: durable facts about each user, extracted from conversations by Flash-Lite.

Facts are a short list injected into the prompt (not embeddings: the embedding quota is shared with RAG).
Scope "family" facts (household, shared people/events) are visible only to users who opted in.
"""

import json
import threading

from app import config, llm, sessions
from app.prompt import now_line

EVERY_N_USER_MESSAGES = 2
MAX_IN_PROMPT = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'user', text TEXT NOT NULL,
    conversation TEXT, created DATETIME DEFAULT CURRENT_TIMESTAMP, updated DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_mem_user ON memories(user, updated);
CREATE TABLE IF NOT EXISTS users (user TEXT PRIMARY KEY, share_family INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS memory_progress (conversation TEXT PRIMARY KEY, upto INTEGER NOT NULL);
"""

EXTRACT_SYSTEM = """Jsi paměť postavy „Ten druhý“ – vnitřního hlasu uživatele. Z nového úseku konverzace vytáhni \
TRVALÉ informace o UŽIVATELI, které stojí za zapamatování na týdny dopředu: lidé v jeho životě (jména, vztahy), \
práce, koníčky, zdraví, zvyky, preference, důležité plány a události (s datem), jeho obavy a radosti.
Dostaneš jen zprávy uživatele (bez odpovědí Toho druhého). Krátké odpovědi bez kontextu („jo“, „ne“) ignoruj.
Plány, termíny a události s datem ukládej VŽDY, i pracovní a i když jsou zmíněné jen mimochodem v jiné větě („potřebuju schválení pro zítřejší deploy“ → ulož i ten deploy s datem). Ty jsou nejcennější.
NEUKLÁDEJ: obsah knih, běžné tlachání, jednorázové drobnosti („jdu si pro kafe“), testovací zprávy.
Relativní data převeď na absolutní podle aktuálního data (např. „zítra deploy“ → „deploy na produkci v sobotu 3. 10. 2026“).
Fakta piš česky, krátce, ve 3. osobě („Má dceru Emu (8 let).“).
scope: "family" jen pro fakta o společné domácnosti/rodině (děti, partner, domácí mazlíčci, společné akce), jinak "user".

Dostaneš EXISTUJÍCÍ paměť (s id) a NOVÝ úsek. Vrať JSON:
{"add": [{"text": "...", "scope": "user|family"}], "update": [{"id": 12, "text": "..."}], "delete": [7]}
- update: když nový úsek existující fakt upřesňuje nebo mění (např. deploy proběhl → aktualizuj).
- delete: fakt už neplatí nebo ho uživatel výslovně chce zapomenout.
- Žádné duplicity. Když není nic nového, vrať {"add": [], "update": [], "delete": []}."""

_running: set[str] = set()
_lock = threading.Lock()


def _db():
    db = sessions.db()
    if not getattr(_db, "ready", False):
        db.executescript(SCHEMA)
        _db.ready = True
    return db


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    _db()
    return sessions._q(sql, args)


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


def visible(user: str) -> list[dict]:
    """The user's own facts plus family facts from opted-in users (if this user opted in too)."""
    if shares_family(user):
        rows = _q("""SELECT m.id, m.user, m.scope, m.text, m.updated FROM memories m
                     LEFT JOIN users u ON u.user = m.user
                     WHERE m.user = ? OR (m.scope = 'family' AND u.share_family = 1)
                     ORDER BY m.updated DESC LIMIT ?""", (user, MAX_IN_PROMPT))
    else:
        rows = _q("SELECT id, user, scope, text, updated FROM memories WHERE user = ? ORDER BY updated DESC LIMIT ?",
                  (user, MAX_IN_PROMPT))
    return [{"id": i, "user": u, "scope": s, "text": t, "updated": d, "own": u == user} for i, u, s, t, d in rows]


def delete(user: str, memory_id: int) -> bool:
    if not _q("SELECT 1 FROM memories WHERE id = ? AND user = ?", (memory_id, user)):
        return False
    _q("DELETE FROM memories WHERE id = ?", (memory_id,))
    return True


def prompt_block(user: str) -> str:
    facts = visible(user)
    if not facts:
        return ""
    lines = "\n".join(f"- {f['text']}" + ("" if f["own"] else f" (ví to od: {f['user']})") for f in reversed(facts))
    return ("## Co o něm víš (tvoje dlouhodobá paměť)\n"
            "Ber to jako samozřejmost, co prostě víš. Vytáhni to jen když se to hodí – nikdy to nevyjmenovávej "
            "a nepřiznávej, že máš „paměť“.\n" + lines)


def _apply(user: str, conversation: str, ops: dict, own_ids: set[int]):
    for a in ops.get("add") or []:
        text = (a.get("text") or "").strip()
        if text:
            scope = "family" if a.get("scope") == "family" else "user"
            _q("INSERT INTO memories(user, scope, text, conversation) VALUES (?, ?, ?, ?)", (user, scope, text, conversation))
    for u in ops.get("update") or []:
        if u.get("id") in own_ids and (u.get("text") or "").strip():
            _q("UPDATE memories SET text = ?, updated = CURRENT_TIMESTAMP, conversation = ? WHERE id = ?",
               (u["text"].strip(), conversation, u["id"]))
    for i in ops.get("delete") or []:
        if i in own_ids:
            _q("DELETE FROM memories WHERE id = ?", (i,))


def extract(user: str, conversation: str, force: bool = False):
    """Process messages after the last processed one; runs every EVERY_N_USER_MESSAGES user turns."""
    rows = _q("SELECT upto FROM memory_progress WHERE conversation = ?", (conversation,))
    upto = rows[0][0] if rows else 0
    new = [m for m in sessions.messages(conversation) if m["id"] > upto]
    if not new or (not force and sum(m["role"] == "user" for m in new) < EVERY_N_USER_MESSAGES):
        return
    own = [f for f in visible(user) if f["own"]]
    existing = "\n".join(f"[{f['id']}] ({f['scope']}) {f['text']}" for f in own) or "(prázdná)"
    # Only the user's own words: his sarcastic questions ("Že ti to schválíme za nich?") got read as facts.
    convo = "\n".join(f"Uživatel: {m['content']}" for m in new if m["role"] == "user" and m["content"])
    user_msg = f"Aktuální datum: {now_line()}\n\nEXISTUJÍCÍ paměť:\n{existing}\n\nNOVÝ úsek konverzace:\n{convo}"
    ops = json.loads(llm.generate(EXTRACT_SYSTEM, user_msg, json_mode=True, temperature=0, patient=False))
    _apply(user, conversation, ops, {f["id"] for f in own})
    _q("INSERT INTO memory_progress(conversation, upto) VALUES (?, ?) ON CONFLICT(conversation) DO UPDATE SET upto = excluded.upto",
       (conversation, new[-1]["id"]))


def changed_since(user: str, conversation: str, after_id: int) -> list[dict]:
    """Facts added/updated from this conversation after a given memory id/time marker (for the 🧠 note in the UI)."""
    rows = _q("SELECT id, text FROM memories WHERE user = ? AND conversation = ? AND (id > ? OR updated >= datetime('now', '-30 seconds'))"
              " ORDER BY id", (user, conversation, after_id))
    return [{"id": i, "text": t} for i, t in rows]


def max_id() -> int:
    rows = _q("SELECT COALESCE(MAX(id), 0) FROM memories")
    return rows[0][0]


def sweep(idle_minutes: int = 10):
    """Process leftover messages (odd counts, last turns) in conversations idle for a while."""
    rows = _q("""SELECT c.id, c.user FROM conversations c
                 WHERE c.updated <= datetime('now', ?)
                 AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation = c.id AND m.role = 'user'
                             AND m.id > COALESCE((SELECT upto FROM memory_progress p WHERE p.conversation = c.id), 0))""",
              (f"-{idle_minutes} minutes",))
    for cid, user in rows:
        try:
            extract(user, cid, force=True)
        except Exception as e:
            print(f"  [memory] sweep {cid[:8]}: {str(e)[:80]}", flush=True)


def extract_async(user: str, conversation: str):
    """Fire-and-forget after a reply; one extraction per conversation at a time."""
    with _lock:
        if conversation in _running:
            return
        _running.add(conversation)

    def run():
        try:
            extract(user, conversation)
        except Exception as e:  # quota / bad JSON: try again after the next messages
            print(f"  [memory] skipped: {str(e)[:100]}", flush=True)
        finally:
            with _lock:
                _running.discard(conversation)

    threading.Thread(target=run, daemon=True).start()
