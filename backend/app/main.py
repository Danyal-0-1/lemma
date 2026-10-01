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
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.build.coordinator import build_from_spec
from app.db import init_db
from app.demo import run_demo
from app.events import event_bus
from app.ideation import repo
from app.ideation.control import cancel_session, resolve_approval, start_session
from app.ideation.export import render_session_markdown
from app.lab import repo as lab_repo
from app.lab import workflows as lab_workflows
from app.lab.advanced_routes import router as lab_advanced_router
from app.lab.automation import automation_runner
from app.lab.evaluation import evaluation_runner
from app.lab.orchestrator import lab_orchestrator
from app.lab.routes import router as lab_router
from app.lab.source_routes import router as lab_source_router
from app.oneshot import run_oneshot
from app.security import LocalOnlyMiddleware, websocket_is_trusted
from app.settings import get_settings
from app.state_vault import sync_loop as sync_state_vault_loop
from app.state_vault import sync_vault
from app.teach.explain import run_explain
from app.terminal.pty_service import connect_pty, create_terminal
from app.workspaces import checks, github, manager, source_control
from app.workspaces.diff import compute_diff
from app.workspaces.files import build_tree, list_files, read_file
from app.ws import connect_websocket

# The three decisions the founder can make at the approval gate.
VALID_DECISIONS = {"approve", "changes", "reject"}

# A single version string surfaced in /health and (later) the `hello` WS event, so the
# frontend can tell which backend it's talking to.
SERVER_VERSION = "0.3.0"

# The frontend and backend use different ports in development. Unlike the original
# any-loopback-port regex, this exact list does not trust an unrelated local web app.
ALLOWED_FRONTEND_ORIGINS = get_settings().allowed_frontend_origins()

# Practical request bounds. These are deliberately generous for research prompts while
# preventing a single local request from consuming unbounded memory or provider spend.
MAX_SEED_CHARS = 20_000
MAX_FEEDBACK_CHARS = 20_000
MAX_EXPLAIN_CONTENT_CHARS = 200_000
MAX_CONTEXT_LABEL_CHARS = 256

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
    recovered = await asyncio.to_thread(lab_repo.recover_stale_runs)
    if recovered:
        logger.warning("recovered %d interrupted research run(s) as failed", recovered)
    advanced_recovered = await asyncio.to_thread(lab_workflows.recover_interrupted_work)
    if any(advanced_recovered.values()):
        logger.warning(
            "recovered interrupted advanced work as failed: %s",
            advanced_recovered,
        )

    # Keep a human-reviewable local Git history of the durable application state.
    # The vault has no remote by default and this process never pushes it.
    vault_stop: asyncio.Event | None = None
    vault_task: asyncio.Task[None] | None = None
    if settings.auto_git_vault:
        try:
            await asyncio.to_thread(sync_vault)
        except Exception:
            # A missing/broken Git installation must not turn the desktop into a
            # blank screen. Source Control will surface the actionable Git error.
            logger.exception("initial application-state snapshot failed")
        vault_stop = asyncio.Event()
        vault_task = asyncio.create_task(sync_state_vault_loop(vault_stop))

    # Soft guard: warn (don't crash) if we'd try to call real models with no key.
    if not settings.mock_llm and not settings.has_any_key():
        logger.warning(
            "MOCK_LLM=false but no provider API key is set — real model calls will fail. "
            "Add a key to backend/.env or set MOCK_LLM=true."
        )

    mode = "MOCK (no keys, no cost)" if settings.mock_llm else "LIVE (real model calls)"
    logger.info("Lemma backend v%s starting — %s", SERVER_VERSION, mode)
    logger.info("Serving on http://%s:%d", settings.host, settings.port)

    try:
        yield  # ── the app serves requests while suspended here ──
    finally:
        # Persist cancellation before closing the database so no new background
        # feature leaves a misleading "running" row across a restart.
        await asyncio.gather(
            lab_orchestrator.shutdown(),
            evaluation_runner.shutdown(),
            automation_runner.shutdown(),
            return_exceptions=True,
        )
        if vault_stop is not None and vault_task is not None:
            vault_stop.set()
            await vault_task
            try:
                await asyncio.to_thread(sync_vault)
            except Exception:
                logger.exception("final application-state snapshot failed")
        logger.info("Lemma backend shutting down.")


# The application object uvicorn imports and runs. The lifespan handler above wires in
# our startup checks.
app = FastAPI(title="Lemma", version=SERVER_VERSION, lifespan=lifespan)

# CORS lets the browser (served from the Vite port) call this API (served from :8000).
# We allow only local origins — never "*" — because this server runs shell commands.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
# This also checks the actual peer address, closing the gap between the HOST setting
# and a Uvicorn command-line --host override.
app.add_middleware(LocalOnlyMiddleware, allowed_origins=ALLOWED_FRONTEND_ORIGINS)
app.include_router(lab_router)
app.include_router(lab_advanced_router)
app.include_router(lab_source_router)


def _require_host_execution() -> None:
    """Reject host process execution unless the local operator explicitly enabled it."""
    if not get_settings().enable_host_execution:
        raise HTTPException(
            status_code=403,
            detail="host execution is disabled; set ENABLE_HOST_EXECUTION=true to opt in",
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
        "enable_host_execution": settings.enable_host_execution,
        "enable_headless_coding": settings.enable_headless_coding,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """The single event stream: every subsystem's output reaches the browser here.

    Exists as the outbound pipe. The real work (subscribe, hello, pump, heartbeat,
    clean disconnect) lives in ws.py so this route stays a one-liner — the pattern
    every reader can predict.
    """
    if not websocket_is_trusted(websocket, ALLOWED_FRONTEND_ORIGINS):
        await websocket.close(code=1008, reason="untrusted websocket origin")
        return
    await connect_websocket(websocket, event_bus, SERVER_VERSION)


@app.post("/api/demo")
async def demo() -> dict[str, str]:
    """Kick off the scripted fake crew round (M1) and return its session id.

    Exists so the frontend's "Play demo" button has something to call. We launch the
    demo as a background task and return immediately — the conversation then streams
    in over /ws, exactly as a real ideation session will.
    """
    session_id = f"ideation_{uuid4().hex}"
    # Fire-and-forget: the task publishes events on its own; the HTTP call is just the trigger.
    asyncio.create_task(run_demo(session_id))
    return {"session_id": session_id}


class OneshotRequest(BaseModel):
    """Body for POST /api/oneshot: the seed idea to hand the Generator."""

    model_config = ConfigDict(extra="forbid")

    # A sensible default so the button works with no typing; the composer supplies
    # a real seed in M3.
    seed: str = Field(
        default="a small tool that helps me build better habits",
        min_length=1,
        max_length=MAX_SEED_CHARS,
    )


@app.post("/api/oneshot")
async def oneshot(request: OneshotRequest) -> dict[str, str]:
    """Stream a single real (or mock) Generator turn and return its session id.

    Exists as M2's end-to-end test: this is the first endpoint that calls a model
    through the provider layer, prices the result, and moves the cost meter. Like the
    demo, it runs in the background and streams over /ws.
    """
    session_id = f"ideation_{uuid4().hex}"
    asyncio.create_task(run_oneshot(session_id, request.seed))
    return {"session_id": session_id}


# ── Ideation sessions (the real crew, M3) ────────────────────────────────────


class SessionRequest(BaseModel):
    """Body for POST /api/sessions: the founder's seed idea to start the crew."""

    model_config = ConfigDict(extra="forbid")

    seed: str = Field(min_length=1, max_length=MAX_SEED_CHARS)


class ApprovalRequest(BaseModel):
    """Body for POST /api/sessions/{id}/approve: the founder's decision at the gate."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "changes", "reject"]
    feedback: str | None = Field(default=None, max_length=MAX_FEEDBACK_CHARS)


@app.post("/api/sessions")
async def create_session(request: SessionRequest) -> dict[str, str]:
    """Start a full ideation crew run for a seed. The debate streams over /ws."""
    session_id = f"ideation_{uuid4().hex}"
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
    except (ValueError, RuntimeError) as error:
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
    _require_host_execution()
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        path = await asyncio.to_thread(manager.validated_workspace_path, workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    result = await asyncio.to_thread(manager.open_in_editor, path)
    return {"result": result}


@app.post("/api/workspaces/{workspace_id}/reveal")
async def reveal_workspace(workspace_id: str) -> dict[str, str]:
    """Reveal the workspace folder in the OS file manager."""
    _require_host_execution()
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        path = await asyncio.to_thread(manager.validated_workspace_path, workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    result = await asyncio.to_thread(manager.reveal, path)
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
    _require_host_execution()
    workspace = await asyncio.to_thread(manager.get_workspace, request.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        path = await asyncio.to_thread(manager.validated_workspace_path, workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    terminal_id = create_terminal(path)
    return {"terminal_id": terminal_id}


@app.websocket("/pty/{terminal_id}")
async def pty_endpoint(websocket: WebSocket, terminal_id: str) -> None:
    """Raw byte stream between the browser terminal and the workspace shell.

    Kept separate from /ws (which carries the JSON event envelope) so terminal bytes
    stay off the event bus — see ARCHITECTURE.md.
    """
    if not get_settings().enable_host_execution:
        await websocket.close(code=1008, reason="host execution disabled")
        return
    if not websocket_is_trusted(websocket, ALLOWED_FRONTEND_ORIGINS):
        await websocket.close(code=1008, reason="untrusted websocket origin")
        return
    await connect_pty(websocket, terminal_id)


# ── Diff / Files / Checks (the review loop, M6) ──────────────────────────────


async def _require_workspace_path(workspace_id: str) -> str:
    """Return a workspace's directory path, or raise 404. Shared by the M6 routes."""
    workspace = await asyncio.to_thread(manager.get_workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        return await asyncio.to_thread(manager.validated_workspace_path, workspace)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get("/api/workspaces/{workspace_id}/tree")
async def get_workspace_tree(workspace_id: str) -> dict:
    """Return a bounded hierarchy for the VS Code-style Explorer."""
    path = await _require_workspace_path(workspace_id)
    return await asyncio.to_thread(build_tree, path)


@app.get("/api/workspaces/{workspace_id}/file")
async def get_file(workspace_id: str, path: str, ref: str = "working") -> dict:
    """Return one file's content — working tree, or the committed version (ref=head)."""
    workspace_path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(read_file, workspace_path, path, ref)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class GitPathsRequest(BaseModel):
    """A bounded set of literal workspace paths to stage or unstage."""

    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(min_length=1, max_length=source_control.MAX_MUTATION_PATHS)


class GitCommitRequest(BaseModel):
    """A human-authored commit message; Git hooks and signing remain disabled."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=source_control.MAX_COMMIT_MESSAGE_CHARS)


class GitPushRequest(BaseModel):
    """An explicitly confirmed push of current HEAD to its configured upstream."""

    model_config = ConfigDict(extra="forbid")

    remote: str = Field(min_length=1, max_length=64)
    branch: str = Field(min_length=1, max_length=255)
    confirm: bool = False


class GitRemoteRequest(BaseModel):
    """A credential-free github.com remote and optional initial branch tracking."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2_048)
    set_upstream: bool = False


def _source_control_http_error(error: source_control.SourceControlError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@app.get("/api/github/status")
async def get_github_status() -> dict[str, object]:
    """Inspect the local GitHub CLI account without requesting or returning a token."""
    return await asyncio.to_thread(github.github_connection_status)


@app.get("/api/workspaces/{workspace_id}/git/status")
async def get_git_status(workspace_id: str) -> dict[str, object]:
    """Read branch and working-tree state without enabling host mutations."""
    path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(source_control.git_status, path)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


@app.get("/api/workspaces/{workspace_id}/git/remotes")
async def get_git_remotes(workspace_id: str) -> dict[str, object]:
    """Return credential-redacted Git remote and GitHub connection information."""
    path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(source_control.git_remote_info, path)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


@app.put("/api/workspaces/{workspace_id}/git/remotes/{remote}")
async def put_git_remote(
    workspace_id: str,
    remote: str,
    body: GitRemoteRequest,
) -> dict[str, object]:
    """Add/update a GitHub remote only after the operator enables host writes."""
    _require_host_execution()
    path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(
            source_control.configure_github_remote,
            path,
            remote,
            body.url,
            set_upstream=body.set_upstream,
        )
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


@app.get("/api/workspaces/{workspace_id}/git/diff")
async def get_git_file_diff(
    workspace_id: str,
    path: str,
    staged: bool = False,
) -> dict[str, object]:
    """Return a bounded textual patch with external diff drivers disabled."""
    workspace_path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(source_control.git_diff, workspace_path, path, staged)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


@app.post("/api/workspaces/{workspace_id}/git/stage")
async def stage_git_paths(workspace_id: str, body: GitPathsRequest) -> dict[str, object]:
    _require_host_execution()
    path = await _require_workspace_path(workspace_id)
    try:
        status = await asyncio.to_thread(source_control.stage_paths, path, body.paths)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error
    return {"ok": True, "status": status}


@app.post("/api/workspaces/{workspace_id}/git/unstage")
async def unstage_git_paths(workspace_id: str, body: GitPathsRequest) -> dict[str, object]:
    _require_host_execution()
    path = await _require_workspace_path(workspace_id)
    try:
        status = await asyncio.to_thread(source_control.unstage_paths, path, body.paths)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error
    return {"ok": True, "status": status}


@app.post("/api/workspaces/{workspace_id}/git/commit")
async def commit_git_changes(workspace_id: str, body: GitCommitRequest) -> dict[str, object]:
    _require_host_execution()
    path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(source_control.commit_changes, path, body.message)
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


@app.post("/api/workspaces/{workspace_id}/git/push")
async def push_git_branch(workspace_id: str, body: GitPushRequest) -> dict[str, object]:
    _require_host_execution()
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="push requires explicit confirmation")
    path = await _require_workspace_path(workspace_id)
    try:
        return await asyncio.to_thread(
            source_control.push_branch,
            path,
            body.remote,
            body.branch,
            confirmed=True,
        )
    except source_control.SourceControlError as error:
        raise _source_control_http_error(error) from error


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
    _require_host_execution()
    path = await _require_workspace_path(workspace_id)
    asyncio.create_task(checks.run_check(workspace_id, path, check_id))
    return {"status": "running"}


# ── Explain / mentor (the teaching layer, M7) ────────────────────────────────


class ExplainRequest(BaseModel):
    """Body for POST /api/explain: what to explain and any surrounding context."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=MAX_EXPLAIN_CONTENT_CHARS)
    question: str | None = Field(default=None, max_length=MAX_FEEDBACK_CHARS)
    context: str | None = Field(default=None, max_length=MAX_EXPLAIN_CONTENT_CHARS)
    context_label: str | None = Field(default=None, max_length=MAX_CONTEXT_LABEL_CHARS)


@app.post("/api/explain")
async def explain(request: ExplainRequest) -> dict[str, str]:
    """Ask the mentor to explain something; the answer streams over /ws as role mentor."""
    session_id = f"explain_{uuid4().hex}"
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
