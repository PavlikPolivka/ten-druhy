"""Conversation store (SQLite). Conversations belong to the Authelia user, so they follow them across devices."""

import sqlite3
import threading
import uuid

from app import config

_lock = threading.Lock()
_db: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, user TEXT NOT NULL, title TEXT,
    created DATETIME DEFAULT CURRENT_TIMESTAMP, updated DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_conv_user ON conversations(user, updated);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, conversation TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conversation, id);
CREATE TABLE IF NOT EXISTS feedback (
    message_id INTEGER PRIMARY KEY, user TEXT NOT NULL, rating INTEGER NOT NULL,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP);
"""


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        config.SESSIONS_DB.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(config.SESSIONS_DB, check_same_thread=False)
        cols = [r[1] for r in _db.execute("PRAGMA table_info(messages)")]
        if "session" in cols:  # pre-conversation schema (browser-scoped sessions): keep it aside
            _db.execute("ALTER TABLE messages RENAME TO messages_legacy")
        _db.executescript(SCHEMA)
        if "image" not in [r[1] for r in _db.execute("PRAGMA table_info(messages)")]:
            _db.execute("ALTER TABLE messages ADD COLUMN image TEXT")
    return _db


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    with _lock:
        cur = db().execute(sql, args)
        rows = cur.fetchall()
        db().commit()
        return rows


def owns(user: str, conversation: str | None) -> bool:
    return bool(conversation) and bool(_q("SELECT 1 FROM conversations WHERE id = ? AND user = ?", (conversation, user)))


def create(user: str) -> str:
    cid = uuid.uuid4().hex
    _q("INSERT INTO conversations(id, user) VALUES (?, ?)", (cid, user))
    return cid


def latest(user: str) -> str | None:
    rows = _q("SELECT id FROM conversations WHERE user = ? ORDER BY updated DESC LIMIT 1", (user,))
    return rows[0][0] if rows else None


def conversations(user: str, limit: int = 100) -> list[dict]:
    rows = _q("""SELECT c.id, c.title, c.updated,
                 (SELECT content FROM messages m WHERE m.conversation = c.id AND m.role = 'user' ORDER BY m.id LIMIT 1)
                 FROM conversations c WHERE c.user = ?
                 AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation = c.id)
                 ORDER BY c.updated DESC LIMIT ?""", (user, limit))
    return [{"id": i, "title": t, "updated": u, "preview": (p or "")[:80]} for i, t, u, p in rows]


def set_title(conversation: str, title: str):
    _q("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation))


def title(conversation: str) -> str | None:
    rows = _q("SELECT title FROM conversations WHERE id = ?", (conversation,))
    return rows[0][0] if rows else None


def delete(user: str, conversation: str) -> bool:
    if not owns(user, conversation):
        return False
    for (name,) in _q("SELECT image FROM messages WHERE conversation = ? AND image IS NOT NULL", (conversation,)):
        (IMAGES / name).unlink(missing_ok=True)
    with _lock:
        db().execute("DELETE FROM feedback WHERE message_id IN (SELECT id FROM messages WHERE conversation = ?)", (conversation,))
        db().execute("DELETE FROM messages WHERE conversation = ?", (conversation,))
        db().execute("DELETE FROM conversations WHERE id = ?", (conversation,))
        db().commit()
    return True


IMAGES = config.SESSIONS_DB.parent / "images"


def save_image(data: bytes) -> str:
    IMAGES.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".jpg"
    (IMAGES / name).write_bytes(data)
    return name


def image_path(user: str, name: str):
    """Path of an image if it belongs to one of the user's conversations."""
    ok = _q("SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation WHERE m.image = ? AND c.user = ?",
            (name, user))
    p = IMAGES / name
    return p if ok and p.is_file() else None


def add(conversation: str, role: str, content: str, image: str | None = None) -> int:
    with _lock:
        cur = db().execute("INSERT INTO messages(conversation, role, content, image) VALUES (?, ?, ?, ?)",
                           (conversation, role, content, image))
        db().execute("UPDATE conversations SET updated = CURRENT_TIMESTAMP WHERE id = ?", (conversation,))
        db().commit()
        return cur.lastrowid


def messages(conversation: str) -> list[dict]:
    rows = _q("SELECT m.id, m.role, m.content, f.rating, m.image FROM messages m"
              " LEFT JOIN feedback f ON f.message_id = m.id WHERE m.conversation = ? ORDER BY m.id", (conversation,))
    return [{"id": i, "role": r, "content": c, "rating": f, "image": im} for i, r, c, f, im in rows]


def rate(user: str, message_id: int, rating: int) -> bool:
    """Thumbs up/down (1/-1, 0 clears) on one of the user's own assistant messages."""
    ok = _q("SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation"
            " WHERE m.id = ? AND m.role = 'assistant' AND c.user = ?", (message_id, user))
    if not ok:
        return False
    if rating:
        _q("INSERT INTO feedback(message_id, user, rating) VALUES (?, ?, ?)"
           " ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating, ts = CURRENT_TIMESTAMP",
           (message_id, user, rating))
    else:
        _q("DELETE FROM feedback WHERE message_id = ?", (message_id,))
    return True


def rated_exchanges() -> list[dict]:
    """Rated replies with the user message before them, for persona tuning."""
    rows = _q("""SELECT f.rating, f.user, f.ts, a.content,
                 (SELECT u.content FROM messages u WHERE u.conversation = a.conversation AND u.id < a.id
                  AND u.role = 'user' ORDER BY u.id DESC LIMIT 1)
                 FROM feedback f JOIN messages a ON a.id = f.message_id ORDER BY f.ts""")
    return [{"rating": r, "user": u, "ts": t, "reply": a, "message": m} for r, u, t, a, m in rows]


RECENT_PHOTOS = 2  # photos re-sent with follow-ups ("o co v tom obrázku jde?"); ~260 tokens each for Gemini


def history(conversation: str, budget_tokens: int = config.HISTORY_TOKENS) -> list[dict]:
    """Most recent turns that fit the token budget, starting with a user turn (Gemini requires it).

    The last RECENT_PHOTOS photos travel along so follow-up questions can refer to them; older ones become a
    "[poslal fotku]" placeholder.
    """
    out, used, photos = [], 0, 0
    for m in reversed(messages(conversation)):
        used += len(m["content"]) // 4
        if used > budget_tokens and out:
            break
        item = {"role": m["role"], "content": m["content"]}
        if m.get("image"):
            path = IMAGES / m["image"]
            if photos < RECENT_PHOTOS and path.is_file():
                item["image"] = (path.read_bytes(), "image/jpeg")
                item["content"] = m["content"] or "(fotka)"
                photos += 1
            else:
                item["content"] = f"[poslal fotku] {m['content']}".strip()
        out.append(item)
    out.reverse()
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out
