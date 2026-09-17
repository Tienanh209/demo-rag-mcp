"""HTTP surface for the demo console.

The chat endpoint returns the answer *and* the execution trace in one payload,
so the UI can show the routing decision beside the answer instead of hiding it
in server logs.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.client import llm, memory
from src.client.mcp_session import MCPConnection
from src.client.orchestrator import Orchestrator
from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("client.web")
WEB_DIR = Path(__file__).resolve().parents[2] / "web"

state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm.require("web console")
    conn = MCPConnection()
    await conn.connect()
    state["mcp"] = conn
    state["orchestrator"] = Orchestrator(conn)
    log.info("client ready on port %d", settings.client_port)
    try:
        yield
    finally:
        await conn.close()


app = FastAPI(title="YZU AI Center assistant", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="demo", max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    lang: str = Field(default="en", pattern="^(en|zh)$")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    orchestrator: Orchestrator = state["orchestrator"]  # type: ignore[assignment]
    try:
        result = await orchestrator.handle(req.session_id, req.message, lang=req.lang)
    except Exception as exc:  # surfaced to the UI rather than swallowed
        log.exception("turn failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.as_dict()


@app.get("/api/status")
async def status():
    conn: MCPConnection = state["mcp"]  # type: ignore[assignment]
    info = await conn.call("index_status")
    return {"transport": settings.mcp_transport, "tools": conn.tools, "index": info}


def _checked_id(session_id: str) -> str:
    """Reject anything that is not a plain id before it is used as a filename."""
    if not memory.valid_session_id(session_id):
        raise HTTPException(status_code=400, detail="invalid session id")
    return session_id


@app.get("/api/sessions")
async def sessions():
    return {"sessions": memory.list_sessions()}


@app.post("/api/sessions")
async def new_session():
    # Nothing is written until the first turn, so an abandoned session leaves
    # no file behind.
    return {"session_id": f"s-{uuid4().hex[:8]}"}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    mem = memory.get_memory(_checked_id(session_id))
    return {
        "session_id": mem.session_id,
        "title": mem.title,
        "summary": mem.summary,
        "turns": [
            {
                "role": t.role,
                "content": t.content,
                "citations": t.citations,
                "grounded": t.grounded,
                "intent": t.intent,
            }
            for t in mem.turns
        ],
    }


@app.delete("/api/sessions/{session_id}")
async def remove_session(session_id: str):
    return {"ok": memory.delete_session(_checked_id(session_id))}


@app.get("/healthz")
async def healthz():
    return {"ok": state.get("mcp") is not None}


@app.get("/")
async def index():
    # Always revalidate the shell. A cached index.html paired with a fresh
    # app.js is a version mismatch that throws at load and blanks the page —
    # the static assets under /static still cache normally via ETag.
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


# Mounted last so it cannot shadow the routes above.
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.client_host, port=settings.client_port, log_level="info")


if __name__ == "__main__":
    main()
