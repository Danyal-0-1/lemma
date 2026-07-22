# ─────────────────────────────────────────────────────────────────────────────
# test_orchestrator.py — run the whole crew against the MockProvider.
# READING ORDER: backend #29  (teaches: testing an event-driven async state machine)
#
# Two behaviors matter most: (1) a full round reaches the human gate with a VALID
# Spec persisted, and (2) a tiny token budget stops the run gracefully. We observe
# the run by subscribing to the event bus — the same way the /ws endpoint does.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio

import pytest
from sqlmodel import SQLModel, create_engine

from app import db
from app.config import AppConfig, BudgetConfig, get_config
from app.events import Event, event_bus
from app.ideation import orchestrator as orch_mod
from app.ideation import repo
from app.ideation.orchestrator import IdeationOrchestrator, SessionControl
from app.ideation.schema import Spec


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the db module at a throwaway SQLite file with the tables created."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return engine


async def _drain_until(queue: asyncio.Queue, event_name: str, timeout: float = 20) -> list[Event]:
    """Collect bus events until one named `event_name` arrives (or time out)."""
    collected: list[Event] = []

    async def _loop() -> None:
        while True:
            event = await queue.get()
            collected.append(event)
            if event.event == event_name:
                return

    await asyncio.wait_for(_loop(), timeout)
    return collected


async def test_full_round_reaches_gate_with_valid_spec(temp_db) -> None:
    """Seed → 4 roles → awaiting_approval, with a valid Spec artifact persisted."""
    queue = event_bus.subscribe()
    try:
        control = SessionControl()
        orchestrator = IdeationOrchestrator("ideation_t1", "a habit tracker", control)
        task = asyncio.create_task(orchestrator.run())

        events = await _drain_until(queue, "awaiting_approval")

        # All four roles took a turn.
        started = {e.payload["role"] for e in events if e.event == "agent_turn_started"}
        assert {"generator", "researcher", "critic", "pm"} <= started

        # A Spec artifact was persisted and it validates against the schema.
        spec_artifacts = [a for a in repo.get_artifacts("ideation_t1") if a.kind == "spec"]
        assert spec_artifacts, "expected at least one spec artifact"
        spec = Spec.model_validate_json(spec_artifacts[-1].content_json)
        assert 3 <= len(spec.core_features) <= 7

        # Approve to let the run finish, then confirm the terminal status.
        control.decision = "approve"
        control.approval.set()
        await asyncio.wait_for(task, timeout=10)
        session = repo.get_session_row("ideation_t1")
        assert session is not None and session.status == "approved"
    finally:
        event_bus.unsubscribe(queue)


async def test_tiny_budget_stops_gracefully(temp_db, monkeypatch) -> None:
    """A 1-token budget makes the run emit budget_exceeded and stop, without crashing."""
    base = get_config()
    tiny = AppConfig(
        roles=base.roles,
        budget=BudgetConfig(max_session_tokens=1, max_rounds=3),
        pricing=base.pricing,
    )
    # The orchestrator reads get_config() in __init__; patch the name it looks up.
    monkeypatch.setattr(orch_mod, "get_config", lambda: tiny)

    queue = event_bus.subscribe()
    try:
        control = SessionControl()
        orchestrator = IdeationOrchestrator("ideation_budget", "seed", control)
        task = asyncio.create_task(orchestrator.run())

        events = await _drain_until(queue, "budget_exceeded")
        assert any(e.event == "budget_exceeded" for e in events)

        await asyncio.wait_for(task, timeout=10)
        session = repo.get_session_row("ideation_budget")
        assert session is not None and session.status == "budget_stopped"
    finally:
        event_bus.unsubscribe(queue)
