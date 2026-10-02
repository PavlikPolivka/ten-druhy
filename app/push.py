"""Web Push: VAPID keys, per-user subscriptions, sending notifications."""

import base64
import json
import threading

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from app import config, sessions

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY, user TEXT NOT NULL, sub TEXT NOT NULL, created DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_push_user ON push_subs(user);
"""
KEY_FILE = config.SESSIONS_DB.parent / "vapid_private.pem"
_vapid: Vapid | None = None
_lock = threading.Lock()
_ready = False


def _q(sql: str, args: tuple = ()) -> list[tuple]:
    global _ready
    if not _ready:
        sessions.db().executescript(SCHEMA)
        _ready = True
    return sessions._q(sql, args)


def vapid() -> Vapid:
    """VAPID key pair, generated once and kept in the data volume (backed up with the rest of data/state)."""
    global _vapid
    with _lock:
        if _vapid is None:
            if KEY_FILE.exists():
                _vapid = Vapid.from_file(str(KEY_FILE))
            else:
                KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _vapid = Vapid()
                _vapid.generate_keys()
                _vapid.save_key(str(KEY_FILE))
    return _vapid


def public_key() -> str:
    """Uncompressed EC point, base64url — what the browser's pushManager.subscribe wants."""
    raw = vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def subscribe(user: str, sub: dict):
    _q("INSERT INTO push_subs(endpoint, user, sub) VALUES (?, ?, ?)"
       " ON CONFLICT(endpoint) DO UPDATE SET user = excluded.user, sub = excluded.sub",
       (sub["endpoint"], user, json.dumps(sub)))


def unsubscribe(user: str, endpoint: str):
    _q("DELETE FROM push_subs WHERE endpoint = ? AND user = ?", (endpoint, user))


def users() -> list[str]:
    return [u for (u,) in _q("SELECT DISTINCT user FROM push_subs")]


def has_subscription(user: str) -> bool:
    return bool(_q("SELECT 1 FROM push_subs WHERE user = ?", (user,)))


def send(user: str, title: str, body: str, url: str = "/") -> int:
    """Send to all of the user's devices; drops subscriptions the push service says are gone. Returns #delivered."""
    sent = 0
    for endpoint, sub in _q("SELECT endpoint, sub FROM push_subs WHERE user = ?", (user,)):
        try:
            webpush(json.loads(sub), json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=vapid(), vapid_claims={"sub": config.PUSH_CONTACT}, ttl=6 * 3600)
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            print(f"  [push] {user}: {status} {str(e)[:80]}", flush=True)
            if status in (404, 410):
                _q("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
        except Exception as e:  # network trouble to the push service must not kill the scheduler
            print(f"  [push] {user}: {str(e)[:80]}", flush=True)
    return sent
