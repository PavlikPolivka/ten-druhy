"""API behind the memory screen (tabs: Profil, Fakta, Lidé, Kronika, Sny, Noc, Smyčky). Design: docs/MEMORY.md."""

import json
import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import dream, memory, tts

router = APIRouter(prefix="/api/memory")


def _user(request: Request) -> str:
    from app.main import _user as main_user  # one place resolves the Authelia identity
    return main_user(request)


def _own_fact(user: str, fid: int) -> dict:
    f = memory.get(fid)
    if not f or f["user"] != user:
        raise HTTPException(404)
    return f


@router.get("/overview")
def overview(request: Request):
    user = _user(request)
    dream._q("SELECT 1")  # make sure dream tables exist
    p = memory.profile(user)
    last = dream.last_dream(user)
    return {
        "profile": p,
        "facts": memory.facts(user),
        "upcoming": memory.upcoming(user, 14),
        "episodes": memory.recent_episodes(user, hours=72, limit=60),
        "archived_count": len(memory.facts(user, status="archived", include_family=False)),
        "categories": memory.CATEGORIES,
        "last_dream": last,
        "dreams_in_brief": dream.dreams_in_brief(user),
        "loops": dream.open_items(user),
    }


@router.get("/archive")
def archive(request: Request):
    return memory.facts(_user(request), status="archived", include_family=False)


class FactPatch(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    pinned: bool | None = None
    category: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None


@router.patch("/facts/{fid}")
def patch_fact(fid: int, body: FactPatch, request: Request):
    user = _user(request)
    before = _own_fact(user, fid)
    kw = {k: v for k, v in body.model_dump().items() if v is not None}
    if "category" in kw and kw["category"] not in memory.CATEGORIES:
        raise HTTPException(400, "bad category")
    if "status" in kw and kw["status"] not in ("active", "archived"):
        raise HTTPException(400, "bad status")
    if "pinned" in kw:
        kw["pinned"] = int(kw["pinned"])
    memory.update_fact(fid, **kw)
    dream._log(None, user, fid, "edit", before, memory.get(fid), "upraveno ručně")
    return memory.get(fid)


@router.delete("/facts/{fid}")
def delete_fact(fid: int, request: Request):
    user = _user(request)
    before = _own_fact(user, fid)
    dream._log(None, user, fid, "forget", before, None, "smazáno ručně")
    memory.delete(user, fid)
    return {"ok": True}


@router.post("/facts/{fid}/confirm")
def confirm_inference(fid: int, request: Request):
    """An inference the user says is true becomes a fact."""
    user = _user(request)
    before = _own_fact(user, fid)
    memory.update_fact(fid, kind="fact", confidence=0.95, evidence=before["evidence"] + 1)
    dream._log(None, user, fid, "confirm", before, memory.get(fid), "potvrzeno")
    return memory.get(fid)


@router.post("/facts/{fid}/reject")
def reject_inference(fid: int, request: Request):
    """Wrong inference: deleted, and the dream is told never to infer it again."""
    user = _user(request)
    before = _own_fact(user, fid)
    dream._q("INSERT INTO rejected_inferences(user, text) VALUES (?, ?)", (user, before["text"]))
    dream._log(None, user, fid, "reject", before, None, "odmítnutý odhad")
    memory.delete(user, fid)
    return {"ok": True}


class FactIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    category: str = "ostatní"


@router.post("/facts")
def add_fact(body: FactIn, request: Request):
    user = _user(request)
    fid = memory.add_fact(user, body.text, category=body.category if body.category in memory.CATEGORIES else "ostatní",
                          importance=4, confidence=1.0, pinned=True)
    dream._log(None, user, fid, "add", None, memory.get(fid), "přidáno ručně")
    return memory.get(fid)


class ProfileIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.put("/profile")
def put_profile(body: ProfileIn, request: Request):
    memory.set_profile(_user(request), body.text)
    return {"ok": True}


@router.get("/people")
def people(request: Request):
    rows = dream._q("SELECT name, relation, summary, updated FROM people WHERE user = ? ORDER BY name", (_user(request),))
    return [{"name": n, "relation": r, "summary": s, "updated": u} for n, r, s, u in rows]


@router.get("/chronicle")
def chronicle(request: Request):
    rows = dream._q("SELECT month, text FROM chronicle WHERE user = ? ORDER BY month DESC", (_user(request),))
    return [{"month": m, "text": t} for m, t in rows]


@router.get("/dreams")
def dreams(request: Request):
    rows = dream._q("SELECT id, ts, stats, dream_text, error FROM dreams WHERE user = ? ORDER BY id DESC LIMIT 60",
                    (_user(request),))
    return [{"id": i, "ts": t, "stats": json.loads(s or "{}"), "dream_text": d, "error": e} for i, t, s, d, e in rows]


@router.get("/changes")
def changes(request: Request, dream_id: int | None = None, limit: int = 200):
    user = _user(request)
    if dream_id:
        rows = dream._q("SELECT id, dream_id, fact_id, op, reason, before, after, undone, ts FROM fact_history "
                        "WHERE user = ? AND dream_id = ? ORDER BY id", (user, dream_id))
    else:
        rows = dream._q("SELECT id, dream_id, fact_id, op, reason, before, after, undone, ts FROM fact_history "
                        "WHERE user = ? ORDER BY id DESC LIMIT ?", (user, min(limit, 500)))
    out = []
    for i, d, f, op, reason, before, after, undone, ts in rows:
        b, a = json.loads(before) if before else None, json.loads(after) if after else None
        out.append({"id": i, "dream_id": d, "fact_id": f, "op": op, "reason": reason, "undone": bool(undone), "ts": ts,
                    "before": b and b.get("text"), "after": a and a.get("text")})
    return out


@router.post("/undo/{hid}")
def undo(hid: int, request: Request):
    return {"ok": dream.undo(_user(request), hid)}


class LoopPatch(BaseModel):
    status: str  # done | dismissed


@router.post("/loops/{lid}")
def loop_status(lid: int, body: LoopPatch, request: Request):
    if body.status not in ("done", "dismissed"):
        raise HTTPException(400)
    dream._q("UPDATE open_loops SET status = ? WHERE id = ? AND user = ?", (body.status, lid, _user(request)))
    return {"ok": True}


class SettingsIn(BaseModel):
    dreams_in_brief: bool


@router.post("/settings")
def settings(body: SettingsIn, request: Request):
    dream.set_dreams_in_brief(_user(request), body.dreams_in_brief)
    return {"ok": True}


_dreaming: set[str] = set()


@router.post("/dream")
def dream_now(request: Request):
    """Run tonight's dream now (in the background; the UI polls /dreams)."""
    user = _user(request)
    if user in _dreaming:
        return {"started": False, "reason": "už sním"}
    _dreaming.add(user)

    def run():
        try:
            dream.dream(user)
        except Exception as e:
            print(f"  [dream] manual {user}: {str(e)[:120]}", flush=True)
        finally:
            _dreaming.discard(user)

    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


@router.get("/search")
def search(q: str, request: Request):
    """Search facts (active + archived), episodes and dreams."""
    user = _user(request)
    from app.textnorm import tokens
    qt = set(tokens(q))
    if not qt:
        return []
    hits = []
    for f in memory.facts(user) + memory.facts(user, status="archived", include_family=False):
        n = len(qt & set(tokens(f["text"])))
        if n:
            hits.append({"type": "archiv" if f["status"] == "archived" else "fakt", "id": f["id"], "text": f["text"], "score": n})
    for i, t, ts in dream._q("SELECT id, text, ts FROM episodes WHERE user = ?", (user,)):
        n = len(qt & set(tokens(t)))
        if n:
            hits.append({"type": "postřeh", "id": i, "text": t, "ts": ts, "score": n})
    for i, t, ts in dream._q("SELECT id, dream_text, ts FROM dreams WHERE user = ? AND dream_text IS NOT NULL", (user,)):
        n = len(qt & set(tokens(t)))
        if n:
            hits.append({"type": "sen", "id": i, "text": t, "ts": ts, "score": n})
    return sorted(hits, key=lambda h: -h["score"])[:50]
