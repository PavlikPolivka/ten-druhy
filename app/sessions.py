"""Server-side conversation history in SQLite, trimmed to a token budget."""

import sqlite3
import threading

from app import config

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        config.SESSIONS_DB.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(config.SESSIONS_DB, check_same_thread=False)
        _db.execute(
            "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT,"
            " ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        _db.execute("CREATE INDEX IF NOT EXISTS ix_session ON messages(session, id)")
    return _db


def add(session: str, role: str, content: str):
    with _lock:
        db().execute("INSERT INTO messages(session, role, content) VALUES (?, ?, ?)", (session, role, content))
        db().commit()


def history(session: str, budget_tokens: int = config.HISTORY_TOKENS) -> list[dict]:
    with _lock:
        rows = db().execute(
            "SELECT role, content FROM messages WHERE session = ? ORDER BY id DESC LIMIT 200", (session,)
        ).fetchall()
    out, used = [], 0
    for role, content in rows:
        used += len(content) // 4
        if used > budget_tokens and out:
            break
        out.append({"role": role, "content": content})
    out.reverse()
    while out and out[0]["role"] != "user":  # Gemini wants the conversation to start with the user
        out.pop(0)
    return out


def reset(session: str):
    with _lock:
        db().execute("DELETE FROM messages WHERE session = ?", (session,))
        db().commit()
