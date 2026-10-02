"""OpenAI-compatible API, so Home Assistant Assist, n8n and scripts can talk to him without custom code.

  POST /v1/chat/completions   (stream or not)   model: "ten-druhy"
  GET  /v1/models
  POST /v1/audio/speech       -> WAV (Piper)

Auth: `Authorization: Bearer td_…` (keys created in the settings panel). The key decides the user, so memory,
calendar, reminders and tone all apply. Stateless: the client sends the history; nothing is stored as a conversation.
Meant for the internal `portal` network (http://tendruhy:8000/v1) — it does not go through Authelia.
"""

import json
import time
import uuid

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app import apikeys, tts

router = APIRouter(prefix="/v1")
MODEL = "ten-druhy"


def _auth(authorization: str | None) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = apikeys.verify(token) if token else None
    if not user:
        raise HTTPException(401, {"error": {"message": "invalid API key", "type": "invalid_request_error"}})
    return user


def _text(content) -> str:
    """OpenAI content may be a string or a list of parts; we take the text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


class ChatReq(BaseModel):
    model: str = MODEL
    messages: list[dict]
    stream: bool = False
    user: str | None = None  # OpenAI field; used as the display name if given


@router.get("/models")
def models(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return {"object": "list", "data": [{"id": MODEL, "object": "model", "created": 0, "owned_by": "ten-druhy"}]}


@router.post("/chat/completions")
def chat_completions(req: ChatReq, authorization: str | None = Header(default=None)):
    from app.main import friendly_error, reply_stream  # shared pipeline (main imports this module)

    user = _auth(authorization)
    system = "\n\n".join(_text(m.get("content")) for m in req.messages if m.get("role") in ("system", "developer"))
    turns = [{"role": "assistant" if m["role"] == "assistant" else "user", "content": _text(m.get("content"))}
             for m in req.messages if m.get("role") in ("user", "assistant") and _text(m.get("content"))]
    if not turns or turns[-1]["role"] != "user":
        raise HTTPException(400, {"error": {"message": "last message must be from the user", "type": "invalid_request_error"}})
    message, prev = turns[-1]["content"], turns[:-1]
    while prev and prev[0]["role"] != "user":
        prev.pop(0)
    rid, created = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({"id": rid, "object": "chat.completion.chunk", "created": created, "model": MODEL,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
                                     ensure_ascii=False) + "\n\n"

    if req.stream:
        def events():
            yield chunk({"role": "assistant"})
            try:
                for kind, val in reply_stream(user, req.user or "", prev, message, client_context=system):
                    if kind == "t":
                        yield chunk({"content": val})
            except Exception as e:
                yield chunk({"content": f"[{friendly_error(e)}]"})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    try:
        text = next(v["text"] for k, v in reply_stream(user, req.user or "", prev, message, client_context=system) if k == "done")
    except Exception as e:
        raise HTTPException(503, {"error": {"message": friendly_error(e), "type": "server_error"}})
    return {"id": rid, "object": "chat.completion", "created": created, "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


class SpeechReq(BaseModel):
    input: str
    model: str = "piper"
    voice: str | None = None
    response_format: str = "wav"


@router.post("/audio/speech")
def speech(req: SpeechReq, authorization: str | None = Header(default=None)):
    _auth(authorization)
    if req.response_format not in ("wav", "pcm"):
        raise HTTPException(400, {"error": {"message": "only wav is supported", "type": "invalid_request_error"}})
    audio, _ = tts.synthesize(req.input)
    return Response(audio, media_type="audio/wav")
