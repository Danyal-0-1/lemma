# ─────────────────────────────────────────────────────────────────────────────
# control.py — the registry of running sessions and how the outside world reaches them.
# READING ORDER: backend #27
#
# WHAT THIS FILE DOES:
#   Keeps a map of session_id → SessionControl for every ideation run in progress, and
#   exposes three functions the REST layer calls: start a session, resolve its approval
#   gate, and cancel it. The orchestrator itself (orchestrator.py) is pure state
#   machine; this file is the small "who's running and how do I signal them" layer.
#
# WHY split from the orchestrator: it's a different concern (a lookup table + lifecycle)
#   from the state machine, and separating it keeps orchestrator.py focused on the flow.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio

from app.ideation.orchestrator import IdeationOrchestrator, SessionControl

# The one registry of in-flight sessions. Module-level because there's one backend
# process; each running session has exactly one entry while it's alive.
_active: dict[str, SessionControl] = {}


def start_session(session_id: str, seed: str) -> None:
    """Register a session, launch its orchestrator, and auto-remove it when done."""
    control = SessionControl()
    _active[session_id] = control
    orchestrator = IdeationOrchestrator(session_id, seed, control)

    async def _run_then_cleanup() -> None:
        # Whatever happens in run() (success, error, cancel), drop the registry entry so
        # a finished session can't be approved/cancelled and doesn't leak memory.
        try:
            await orchestrator.run()
        finally:
            _active.pop(session_id, None)

    asyncio.create_task(_run_then_cleanup())


def resolve_approval(session_id: str, decision: str, feedback: str | None = None) -> bool:
    """Deliver the founder's decision to a waiting session. False if it isn't running."""
    control = _active.get(session_id)
    if control is None:
        return False
    control.decision = decision
    control.feedback = feedback
    control.approval.set()  # wake the orchestrator blocked at its gate
    return True


def cancel_session(session_id: str) -> bool:
    """Ask a running session to stop. False if it isn't running."""
    control = _active.get(session_id)
    if control is None:
        return False
    control.cancelled = True
    control.approval.set()  # unblock the gate if it happens to be waiting
    return True
