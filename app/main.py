"""FastAPI app: static chat page + SSE chat endpoint. Auth is handled upstream (Caddy + Authelia)."""

import json
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import llm, retrieval, router, sessions
from app.prompt import system_prompt

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Ten druhý")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _header(request: Request, name: str) -> str:
    """Authelia identity headers (via Caddy copy_headers). Starlette decodes headers as latin-1."""
    raw = request.headers.get(name, "")
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _user(request: Request) -> str:
    # Without Authelia (local dev) everyone is "local".
    return _header(request, "remote-user").strip() or "local"


def _first_name(request: Request) -> str:
    name = _header(request, "remote-name") or _header(request, "remote-user")
    return name.split()[0] if name.strip() else ""


def _search(query: str) -> list[dict]:
    try:
        return retrieval.search(query)
    except Exception as e:  # Qdrant down / collection missing: answer from the lore bible alone
        print(f"  [retrieval] failed: {str(e)[:120]}", flush=True)
        return []


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# The service worker must be served from the root to control the whole app (scope "/").
@app.get("/sw.js")
def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/state")
def state(request: Request, conversation_id: str | None = None):
    """The conversation to show: the requested one if it is the user's, otherwise their latest."""
    user = _user(request)
    cid = conversation_id if sessions.owns(user, conversation_id) else sessions.latest(user)
    return {"name": _first_name(request), "conversation_id": cid, "messages": sessions.messages(cid) if cid else []}


TITLE_SYSTEM = ("Vymysli krátký český název (2–5 slov, bez uvozovek a tečky) pro konverzaci podle první výměny. "
                "Výstižně podle tématu, klidně s lehkou ironií.")


def _make_title(cid: str, message: str, reply: str):
    """Runs in a thread after the reply is streamed, so titling never delays the chat."""
    try:
        t = llm.generate(TITLE_SYSTEM, f"Uživatel: {message}\nOdpověď: {reply}", temperature=0.5, patient=False)
        t = t.strip().strip('"„“.').splitlines()[0][:60] if t.strip() else ""
        if t:
            sessions.set_title(cid, t)
    except Exception as e:
        print(f"  [title] skipped: {str(e)[:80]}", flush=True)


@app.get("/api/conversations")
def list_conversations(request: Request):
    return sessions.conversations(_user(request))


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, request: Request):
    return {"ok": sessions.delete(_user(request), cid)}


class FeedbackIn(BaseModel):
    message_id: int
    rating: int = Field(ge=-1, le=1)


@app.post("/api/feedback")
def feedback(body: FeedbackIn, request: Request):
    return {"ok": sessions.rate(_user(request), body.message_id, body.rating)}


class ChatIn(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    user = _user(request)
    cid = body.conversation_id if sessions.owns(user, body.conversation_id) else sessions.create(user)
    prev = sessions.history(cid)
    last_user = next((m["content"] for m in reversed(prev) if m["role"] == "user"), "")
    name = _first_name(request)

    def events():
        yield _sse({"conversation_id": cid})
        try:
            # Only pull book excerpts when the message is actually about the books.
            about_books, query = router.route(last_user, body.message)
            chunks = _search(query) if about_books else []
            system = system_prompt(chunks, name)
            convo = prev + [{"role": "user", "content": body.message}]
            reply = []
            for piece in llm.stream_chat(system, convo):
                reply.append(piece)
                yield _sse({"t": piece})
            text = "".join(reply).strip()
            mid = None
            if text:
                sessions.add(cid, "user", body.message)
                mid = sessions.add(cid, "assistant", text)
                if not prev and not sessions.title(cid):
                    threading.Thread(target=_make_title, args=(cid, body.message, text), daemon=True).start()
            yield _sse({"done": True, "message_id": mid, "sources": sorted({c["book_title"] for c in chunks})})
        except Exception as e:  # surface errors (e.g. free-tier quota) to the UI instead of a dead stream
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                msg = "Došla denní kvóta Gemini free tieru. Zkus to později."
            yield _sse({"error": msg})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
