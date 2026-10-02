"""API keys for the OpenAI-compatible API: created per user in the settings panel, shown once, stored hashed."""

import hashlib
import secrets

from app import sessions

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,
    created DATETIME DEFAULT CURRENT_TIMESTAMP, last_used DATETIME);
"""
_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        _ready = True
    return sessions._q(sql, args)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(user: str, name: str) -> str:
    token = "td_" + secrets.token_urlsafe(32)
    _q("INSERT INTO api_keys(user, name, hash) VALUES (?, ?, ?)", (user, name.strip()[:60] or "klíč", _hash(token)))
    return token


def verify(token: str) -> str | None:
    rows = _q("SELECT id, user FROM api_keys WHERE hash = ?", (_hash(token),))
    if not rows:
        return None
    _q("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE id = ?", (rows[0][0],))
    return rows[0][1]


def list_(user: str) -> list[dict]:
    rows = _q("SELECT id, name, created, last_used FROM api_keys WHERE user = ? ORDER BY id", (user,))
    return [{"id": i, "name": n, "created": c, "last_used": u} for i, n, c, u in rows]


def revoke(user: str, key_id: int) -> bool:
    if not _q("SELECT 1 FROM api_keys WHERE id = ? AND user = ?", (key_id, user)):
        return False
    _q("DELETE FROM api_keys WHERE id = ?", (key_id,))
    return True
