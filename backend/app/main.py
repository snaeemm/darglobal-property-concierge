import json
import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import _cooldown, chat, last_error
from .config import KEY_FINGERPRINTS, PROVIDERS, RATE_LIMIT_PER_MIN, STATIC_DIR
from .store import get_store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="DarGlobal Property Concierge", docs_url="/api/docs", openapi_url="/api/openapi.json")


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=30)


_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(ip: str):
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Too many messages, please wait a minute.")
    q.append(now)


@app.on_event("startup")
def _load():
    get_store()


@app.get("/api/health")
def health():
    now = time.time()
    return {"ok": True, "models": [f"{p[0]}:{p[3]}" for p in PROVIDERS],
            "cooling_down": {k: round(v - now) for k, v in _cooldown.items() if v > now},
            "keys": KEY_FINGERPRINTS, "last_errors": last_error}


@app.get("/api/stats")
def stats():
    return get_store().stats


@app.get("/api/page")
def page(url: str):
    p = get_store().page(url)
    if not p:
        raise HTTPException(404, "Not in the knowledge base")
    return p


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
    _rate_limit(ip)

    async def events():
        async for ev in chat([m.model_dump() for m in req.messages]):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# React build (single-container deploy)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = STATIC_DIR / path
        return FileResponse(f if path and f.is_file() else STATIC_DIR / "index.html")
