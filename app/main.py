"""FastAPI app: static chat page + SSE chat endpoint. Auth is handled upstream (Caddy + Authelia)."""

import base64
import binascii
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import checkins, llm, memory, push, retrieval, router, sessions, tts, web
from app.prompt import system_prompt

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Ten druhý", on_startup=[checkins.start])
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


def _outside(r: router.Route) -> tuple[str, list[dict]]:
    """Weather / web search context for the prompt + link list for the UI. Failures just mean no context."""
    blocks, links = [], []
    if r.weather:
        try:
            blocks.append(web.weather(r.place or None))
        except Exception as e:
            print(f"  [weather] failed: {str(e)[:100]}", flush=True)
    # A weather question needs no web search once Open-Meteo answered (the router tends to ask for both).
    if r.web and not (r.weather and blocks):
        try:
            hits = web.search(r.web_query)
            blocks.append("Výsledky hledání „" + r.web_query + "“:\n" + "\n".join(
                f"- {h['title']}: {h['snippet']} ({h['url']})" for h in hits))
            links = [{"title": h["title"], "url": h["url"]} for h in hits[:3]]
        except Exception as e:
            print(f"  [web] failed: {str(e)[:100]}", flush=True)
    return "\n\n".join(blocks), links


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


@app.get("/api/memories")
def list_memories(request: Request):
    user = _user(request)
    t, locked = memory.tone(user)
    return {"share_family": memory.shares_family(user), "tone": t, "tone_locked": locked, "items": memory.visible(user)}


@app.get("/api/memories/new")
def new_memories(request: Request, conversation_id: str, after: int = 0):
    """Facts just saved from this conversation (the UI polls once after a reply to show 🧠)."""
    user = _user(request)
    return memory.changed_since(user, conversation_id, after) if sessions.owns(user, conversation_id) else []


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: int, request: Request):
    return {"ok": memory.delete(_user(request), memory_id)}


@app.get("/api/push/key")
def push_key(request: Request):
    return {"key": push.public_key(), "subscribed": push.has_subscription(_user(request))}


class PushSubIn(BaseModel):
    subscription: dict


@app.post("/api/push/subscribe")
def push_subscribe(body: PushSubIn, request: Request):
    if not str(body.subscription.get("endpoint", "")).startswith("https://"):
        raise HTTPException(400, "bad subscription")
    push.subscribe(_user(request), body.subscription)
    return {"ok": True}


class PushUnsubIn(BaseModel):
    endpoint: str


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: PushUnsubIn, request: Request):
    push.unsubscribe(_user(request), body.endpoint)
    return {"ok": True}


@app.post("/api/push/test")
def push_test(request: Request):
    """Like a real check-in: the message lands in a new conversation and the notification opens it."""
    user, text = _user(request), "Tak co, funguje to? Jestli jo, budu se ozývat. Bohužel."
    cid = sessions.create(user)
    sessions.add(cid, "assistant", text)
    sessions.set_title(cid, "Ozval se sám")
    return {"sent": push.send(user, "Ten druhý", text, f"/?c={cid}"), "conversation_id": cid}


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/tts")
def speak(body: TtsIn):
    try:
        audio, engine = tts.synthesize(body.text)
        return Response(audio, media_type="audio/wav", headers={"X-TTS-Engine": engine})
    except Exception:
        raise HTTPException(503, "tts unavailable")  # the browser falls back to its own voice


class SettingsIn(BaseModel):
    share_family: bool | None = None
    tone: str | None = None


@app.post("/api/settings")
def settings(body: SettingsIn, request: Request):
    user = _user(request)
    if body.share_family is not None:
        memory.set_share_family(user, body.share_family)
    if body.tone is not None and not memory.set_tone(user, body.tone):
        raise HTTPException(400, "tone not allowed")
    return {"ok": True}


class FeedbackIn(BaseModel):
    message_id: int
    rating: int = Field(ge=-1, le=1)


@app.post("/api/feedback")
def feedback(body: FeedbackIn, request: Request):
    return {"ok": sessions.rate(_user(request), body.message_id, body.rating)}


@app.get("/api/images/{name}")
def image(name: str, request: Request):
    path = sessions.image_path(_user(request), name) if name.replace(".jpg", "").isalnum() else None
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000"})


class ChatIn(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=64)
    message: str = Field(default="", max_length=4000)
    image: str | None = Field(default=None, max_length=3_000_000)  # base64 JPEG, resized client-side


def _decode_image(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        data = base64.b64decode(b64.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "bad image")
    if not data.startswith(b"\xff\xd8"):  # the client always re-encodes to JPEG
        raise HTTPException(400, "image must be JPEG")
    return data


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    img = _decode_image(body.image)
    if not body.message.strip() and not img:
        raise HTTPException(400, "empty message")
    user = _user(request)
    cid = body.conversation_id if sessions.owns(user, body.conversation_id) else sessions.create(user)
    prev = sessions.history(cid)
    last_user = next((m["content"] for m in reversed(prev) if m["role"] == "user"), "")
    name = _first_name(request)

    def events():
        yield _sse({"conversation_id": cid, "memory_mark": memory.max_id()})
        try:
            # Only pull book excerpts when the message is actually about the books.
            r = router.route(last_user, body.message) if body.message.strip() else router.Route()
            chunks = _search(r.book_query) if r.books else []
            outside, links = _outside(r)
            system = system_prompt(chunks, name, memory.prompt_block(user), outside, memory.tone(user)[0])
            text_in = body.message.strip() or "(posílá ti fotku, bez komentáře)"
            convo = prev + [{"role": "user", "content": text_in, "image": (img, "image/jpeg") if img else None}]
            reply = []
            for piece in llm.stream_chat(system, convo):
                reply.append(piece)
                yield _sse({"t": piece})
            text = "".join(reply).strip()
            mid = None
            if text:
                sessions.add(cid, "user", body.message.strip(), sessions.save_image(img) if img else None)
                mid = sessions.add(cid, "assistant", text)
                memory.extract_async(user, cid)
                if not prev and not sessions.title(cid):
                    threading.Thread(target=_make_title, args=(cid, text_in, text), daemon=True).start()
            yield _sse({"done": True, "message_id": mid, "sources": sorted({c["book_title"] for c in chunks}),
                        "links": links, "weather": r.weather})
        except Exception as e:  # surface errors (e.g. free-tier quota) to the UI instead of a dead stream
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                msg = "Došla denní kvóta Gemini free tieru. Zkus to později."
            yield _sse({"error": msg})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
