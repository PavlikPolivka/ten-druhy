"""FastAPI app: static chat page + SSE chat endpoint. Auth is handled upstream (Caddy + Authelia)."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import llm, retrieval, sessions
from app.prompt import system_prompt

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Ten druhý")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ChatIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn):
    prev = sessions.history(body.session_id)
    # Short follow-ups ("a pak?") retrieve poorly alone; include the previous user turn.
    last_user = next((m["content"] for m in reversed(prev) if m["role"] == "user"), "")
    query = f"{last_user}\n{body.message}" if len(body.message) < 60 else body.message

    def events():
        try:
            chunks = retrieval.search(query)
            system = system_prompt(chunks)
            convo = prev + [{"role": "user", "content": body.message}]
            reply = []
            for piece in llm.stream_chat(system, convo):
                reply.append(piece)
                yield _sse({"t": piece})
            text = "".join(reply).strip()
            if text:
                sessions.add(body.session_id, "user", body.message)
                sessions.add(body.session_id, "assistant", text)
            yield _sse({"done": True, "sources": sorted({c["book_title"] for c in chunks})})
        except Exception as e:  # surface errors (e.g. free-tier quota) to the UI instead of a dead stream
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                msg = "Došla denní kvóta Gemini free tieru. Zkus to později."
            yield _sse({"error": msg})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ResetIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)


@app.post("/api/reset")
def reset(body: ResetIn):
    sessions.reset(body.session_id)
    return {"ok": True}
