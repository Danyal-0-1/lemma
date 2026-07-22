# ─────────────────────────────────────────────────────────────────────────────
# test_checks.py — prove checks persist and that pass/fail is reported correctly.
# READING ORDER: backend #44
#
# A check that succeeds must end with exit_code 0 (green badge); one that fails must end
# non-zero (red badge). We also confirm the command's output is streamed. We observe by
# subscribing to the event bus, exactly like the /ws endpoint does.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio

from app.events import Event, event_bus
from app.workspaces import checks


def _drain(queue: asyncio.Queue) -> list[Event]:
    """Pull every event currently queued (the run already finished)."""
    events: list[Event] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_checks_roundtrip(tmp_path) -> None:
    """write_checks then read_checks returns the same list."""
    saved = [{"id": "c1", "name": "tests", "command": "pytest"}]
    checks.write_checks(str(tmp_path), saved)
    assert checks.read_checks(str(tmp_path)) == saved


async def test_run_check_pass(tmp_path) -> None:
    """A passing check streams its output and finishes with exit_code 0."""
    checks.write_checks(str(tmp_path), [{"id": "ok", "name": "ok", "command": "echo hello-check"}])
    queue = event_bus.subscribe()
    try:
        await checks.run_check("ws1", str(tmp_path), "ok")
        events = _drain(queue)
    finally:
        event_bus.unsubscribe(queue)

    assert any(e.event == "check_started" for e in events)
    finished = next(e for e in events if e.event == "check_finished")
    assert finished.payload["exit_code"] == 0
    output = "".join(e.payload["line"] for e in events if e.event == "check_output")
    assert "hello-check" in output


async def test_run_check_fail(tmp_path) -> None:
    """A failing check finishes with a non-zero exit_code (red badge)."""
    checks.write_checks(str(tmp_path), [{"id": "bad", "name": "bad", "command": "exit 3"}])
    queue = event_bus.subscribe()
    try:
        await checks.run_check("ws1", str(tmp_path), "bad")
        events = _drain(queue)
    finally:
        event_bus.unsubscribe(queue)

    finished = next(e for e in events if e.event == "check_finished")
    assert finished.payload["exit_code"] == 3
