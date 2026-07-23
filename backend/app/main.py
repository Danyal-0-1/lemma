# ─────────────────────────────────────────────────────────────────────────────
# main.py — the FastAPI application: the backend's entry point.
# READING ORDER: backend #5  ← RETYPE THIS (M0)
#
# WHAT THIS FILE DOES:
#   Creates the FastAPI app, configures logging and CORS, runs safety checks at
#   startup, and exposes GET /health so you can confirm the server is alive.
#
# HOW IT FITS:
#   `uv run uvicorn app.main:app` imports the `app` object defined at the bottom.
#   Later milestones attach routers here: /ws (M1), sessions REST (M3), workspaces
#   and /pty (M5). For now it is deliberately tiny so the shape is obvious.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.build.coordinator import build_from_spec
from app.db import init_db
from app.demo import run_demo
from app.events import event_bus
from app.ideation import repo
from app.ideation.control import cancel_session, resolve_approval, start_session
from app.ideation.export import render_session_markdown
from app.oneshot import run_oneshot
from app.settings import get_settings
from app.teach.explain import run_explain
from app.terminal.pty_service import connect_pty, create_terminal
from app.workspaces import checks, manager
from app.workspaces.diff import compute_diff
from app.workspaces.files import list_files, read_file
from app.ws import connect_websocket

# The three decisions the founder can make at the approval gate.
VALID_DECISIONS = {"approve", "changes", "reject"}

# A single version string surfaced in /health and (later) the `hello` WS event, so the
# frontend can tell which backend it's talking to.
SERVER_VERSION = "0.1.0"

# The frontend dev server runs here; the browser will call our API from this origin,
# so CORS must explicitly allow it. (Same host, different port = a "cross origin" request.)
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

logger = logging.getLogger("aicompany")


def _configure_logging(level_name: str) -> None:
    """Set up console logging with timestamps for the whole backend.

    Exists so every module can just call `logging.getLogger(...)` and get consistent,
    timestamped output — and so we obey the rule "no print(), use logging".
    """
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup checks before serving, and (later) clean up on shutdown.

    Exists to fail fast on unsafe configuration and to warn about likely mistakes
    (mock mode off but no API key) at the moment the server boots, rather than deep
    inside a request where the cause would be harder to see.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)

    # Hard guard: never bind a code-executing server beyond localhost by accident.
    settings.assert_safe_binding()

    # Create the SQLite database + tables if needed (used by the cost meter, M2+).
    init_db()

    # Soft guard: warn (don't crash) if we'd try to call real models with no key.
    if not settings.mock_llm and not settings.has_any_key():
        logger.warning(
            "MOCK_LLM=false but no provider API key is set — real model calls will fail. "
            "Add a key to backend/.env or set MOCK_LLM=true."
        )

    mode = "MOCK (no keys, no cost)" if settings.mock_llm else "LIVE (real model calls)"
    logger.info("AI Company backend v%s starting — %s", SERVER_VERSION, mode)
    logger.info("Serving on http://%s:%d", settings.host, settings.port)

    yield  # ── the app serves requests while suspended here ──

    logger.info("AI Company backend shutting down.")


# The application object uvicorn imports and runs. The lifespan handler above wires in
# our startup checks.
app = FastAPI(title="AI Company", version=SERVER_VERSION, lifespan=lifespan)

# CORS lets the browser (served from :5173) call this API (served from :8000).
# We allow only the known frontend origins — not "*" — because this server is powerful.
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe: returns 200 with basic status so tools/UI can confirm we're up.

    Exists as the simplest possible "is the backend alive?" endpoint — used by the
    README's curl check, the frontend's connection logic, and the M0 test.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "version": SERVER_VERSION,
        "mock_llm": settings.mock_llm,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """The single event stream: every subsystem's output reaches the browser here.

    Exists as the outbound pipe. The real work (subscribe, hello, pump, heartbeat,
    clean disconnect) lives in ws.py so this route stays a one-liner — the pattern
    every reader can predict.
    """
    await connect_websocket(websocket, event_bus, SERVER_VERSION)


@app.post("/api/demo")
async def demo() -> dict[str, str]:
    """Kick off the scripted fake crew round (M1) and return its session id.

    Exists so the frontend's "Play demo" button has something to call. We launch the
    demo as a background task and return immediately — the conversation then streams
    in over /ws, exactly as a real ideation session will.
    """
    session_id = f"ideation_{uuid4().hex[:8]}"
    # Fire-and-forget: the task publishes events on its own; the HTTP call is just the trigger.
    asyncio.create_task(run_demo(session_id))
    return {"session_id": session_id}


class OneshotRequest(BaseModel):
    """Body for POST /api/oneshot: the seed idea to hand the Generator."""

    # A sensible default so the button works with no typing; the composer supplies
    # a real seed in M3.
    seed: str = "a small tool that helps me build better habits"


@app.post("/api/oneshot")
async def oneshot(request: OneshotRequest) -> dict[str, str]:
    """Stream a single real (or mock) Generator turn and return its session id.

    Exists as M2's end-to-end test: this is the first endpoint that calls a model
    through the provider layer, prices the result, and moves the cost meter. Like the
    demo, it runs in the background and streams over /ws.
    """
    session_id = f"ideation_{uuid4().hex[:8]}"
    asyncio.create_task(run_oneshot(session_id, request.seed))
    return {"session_id": session_id}


# ── Ideation sessions (the real crew, M3) ────────────────────────────────────


class SessionRequest(BaseModel):
    """Body for POST /api/sessions: the founder's seed idea to start the crew."""

    seed: str


class ApprovalRequest(BaseModel):
    """Body for POST /api/sessions/{id}/approve: the founder's decision at the gate."""

    decision: str  # "approve" | "changes" | "reject"
    feedback: str | None = None


@app.post("/api/sessions")
async def create_session(request: SessionRequest) -> dict[str, str]:
    """Start a full ideation crew run for a seed. The debate streams over /ws."""
    session_id = f"ideation_{uuid4().hex[:8]}"
    start_session(session_id, request.seed)
    return {"session_id": session_id}


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, object]]:
    """List past sessions (newest first) for the sidebar history."""
    sessions = await asyncio.to_thread(repo.list_sessions)
    return [session.model_dump(mode="json") for session in sessions]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, object]:
    """Return one session with its messages and artifacts (for restore/export, M4)."""
    session = await asyncio.to_thread(repo.get_session_row, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = await asyncio.to_thread(repo.get_messages, session_id)
    artifacts = await asyncio.to_thread(repo.get_artifacts, session_id)
    return {
        "session": session.model_dump(mode="json"),
        "messages": [message.model_dump(mode="json") for message in messages],
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }


@app.post("/api/sessions/{session_id}/approve")
async def approve_session(session_id: str, request: ApprovalRequest) -> dict[str, str]:
    """Deliver the founder's gate decision (approve / changes / reject) to the crew."""
    if request.decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=422, detail=f"decision must be one of {sorted(VALID_DECISIONS)}"
        )
    if not resolve_approval(session_id, request.decision, request.feedback):
        raise HTTPException(status_code=404, detail="session not running or not awaiting approval")
    return {"status": "resolved"}


@app.post("/api/sessions/{session_id}/cancel")
async def cancel_session_route(session_id: str) -> dict[str, str]:
    """Ask a running session to stop between turns."""
    if not cancel_session(session_id):
        raise HTTPException(status_code=404, detail="session not running")
    return {"status": "cancelling"}


@app.post("/api/sessions/{session_id}/export")
async def export_session(session_id: str) -> Response:
    """Return the session (transcript + final Spec) as a downloadable markdown file."""
    markdown = await asyncio.to_thread(render_session_markdown, session_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="session not found")
    # Content-Disposition makes the browser save it as a file rather than display it.
    headers = {"Content-Disposition": f'attachment; filename="{session_id}.md"'}
    return Response(content=markdown, media_type="text/markdown", headers=headers)


# ── Workspaces + terminal (Phase 1, M5) ──────────────────────────────────────


class TerminalRequest(BaseModel):
    """Body for POST /api/terminals: which workspace to open a shell in."""

    workspace_id: str


@app.post("/api/workspaces/from-spec/{artifact_id}")
async def create_workspace_from_spec(artifact_id: int) -> dict[str, str]:
    """Build a workspace directory from a Spec artifact and enter the build phase."""
    try:
        workspace = await build_from_spec(artifact_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"workspace_id": workspace.id, "path": workspace.path, "slug": workspace.slug}


@app.get("/api/workspaces")
async def list_workspaces() -> list[dict[str, object]]:
    """List workspaces (newest first) for the sidebar."""
    workspaces = await asyncio.to_thread(manager.list_workspaces)
    return [workspace.model_dump(mode="json") for workspace in workspaces]


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str) -> dict[str, object]:
    """Return one workspace by id."""
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace.model_dump(mode="json")


@app.post("/api/workspaces/{workspace_id}/open-in-editor")
async def open_workspace_in_editor(workspace_id: str) -> dict[str, str]:
    """Open the workspace folder in the user's editor (or reveal it)."""
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    result = await asyncio.to_thread(manager.open_in_editor, workspace.path)
    return {"result": result}


@app.post("/api/workspaces/{workspace_id}/reveal")
async def reveal_workspace(workspace_id: str) -> dict[str, str]:
    """Reveal the workspace folder in the OS file manager."""
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    result = await asyncio.to_thread(manager.reveal, workspace.path)
    return {"result": result}


@app.post("/api/workspaces/{workspace_id}/archive")
async def archive_workspace(workspace_id: str) -> dict[str, str]:
    """Archive a workspace (moves it to History). The directory is kept on disk."""
    workspace = await asyncio.to_thread(manager.set_workspace_status, workspace_id, "archived")
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    event_bus.publish("workspace_archived", {"workspace_id": workspace_id})
    return {"status": "archived"}


@app.post("/api/workspaces/{workspace_id}/restore")
async def restore_workspace(workspace_id: str) -> dict[str, str]:
    """Restore an archived workspace back to the active list."""
    workspace = await asyncio.to_thread(manager.set_workspace_status, workspace_id, "active")
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    event_bus.publish("workspace_restored", {"workspace_id": workspace_id})
    return {"status": "active"}


@app.post("/api/terminals")
async def create_terminal_route(request: TerminalRequest) -> dict[str, str]:
    """Spawn a shell in a workspace and return the terminal id to connect /pty to."""
    workspace = await asyncio.to_thread(manager.get_workspace, request.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    terminal_id = create_terminal(workspace.path)
    return {"terminal_id": terminal_id}


@app.websocket("/pty/{terminal_id}")
async def pty_endpoint(websocket: WebSocket, terminal_id: str) -> None:
    """Raw byte stream between the browser terminal and the workspace shell.

    Kept separate from /ws (which carries the JSON event envelope) so terminal bytes
    stay off the event bus — see ARCHITECTURE.md.
    """
    await connect_pty(websocket, terminal_id)


# ── Diff / Files / Checks (the review loop, M6) ──────────────────────────────


async def _require_workspace_path(workspace_id: str) -> str:
    """Return a workspace's directory path, or raise 404. Shared by the M6 routes."""
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace.path


@app.get("/api/workspaces/{workspace_id}/diff")
async def get_diff(workspace_id: str) -> dict:
    """Return the per-file changes since the last commit (for the Diff tab)."""
    path = await _require_workspace_path(workspace_id)
    return await asyncio.to_thread(compute_diff, path)


@app.get("/api/workspaces/{workspace_id}/files")
async def get_files(workspace_id: str) -> dict:
    """Return the workspace's file list (for the read-only Files tab)."""
    path = await _require_workspace_path(workspace_id)
    return await asyncio.to_thread(list_files, path)


@app.get("/api/workspaces/{workspace_id}/file")
async def get_file(workspace_id: str, path: str, ref: str = "working") -> dict:
    """Return one file's content — working tree, or the committed version (ref=head)."""
    workspace_path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(read_file, workspace_path, path, ref)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class ChecksBody(BaseModel):
    """Body for PUT /checks: the full list of saved checks to persist."""

    checks: list[dict]


@app.get("/api/workspaces/{workspace_id}/checks")
async def get_checks(workspace_id: str) -> dict:
    """Return the workspace's saved checks from aicompany.json."""
    path = await _require_workspace_path(workspace_id)
    return {"checks": await asyncio.to_thread(checks.read_checks, path)}


@app.put("/api/workspaces/{workspace_id}/checks")
async def put_checks(workspace_id: str, body: ChecksBody) -> dict:
    """Save the workspace's checks to aicompany.json."""
    path = await _require_workspace_path(workspace_id)
    await asyncio.to_thread(checks.write_checks, path, body.checks)
    return {"status": "saved"}


@app.post("/api/workspaces/{workspace_id}/checks/{check_id}/run")
async def run_check_route(workspace_id: str, check_id: str) -> dict:
    """Run a saved check; its output streams over /ws (check_started/output/finished)."""
    path = await _require_workspace_path(workspace_id)
    asyncio.create_task(checks.run_check(workspace_id, path, check_id))
    return {"status": "running"}


# ── Explain / mentor (the teaching layer, M7) ────────────────────────────────


class ExplainRequest(BaseModel):
    """Body for POST /api/explain: what to explain and any surrounding context."""

    content: str | None = None  # a selection / a file / a diff to explain
    question: str | None = None  # a free-form question from the composer
    context: str | None = None  # the active tab's content, for grounding
    context_label: str | None = None  # e.g. "diff", "spec", a file path


@app.post("/api/explain")
async def explain(request: ExplainRequest) -> dict[str, str]:
    """Ask the mentor to explain something; the answer streams over /ws as role mentor."""
    session_id = f"explain_{uuid4().hex[:8]}"
    asyncio.create_task(
        run_explain(
            session_id,
            request.content,
            request.question,
            request.context,
            request.context_label,
        )
    )
    return {"session_id": session_id}
