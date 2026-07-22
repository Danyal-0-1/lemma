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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import get_settings

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
