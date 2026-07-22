# ─────────────────────────────────────────────────────────────────────────────
# checks.py — saved verification commands: read/write them, and run them.
# READING ORDER: backend #42
#
# WHAT THIS FILE DOES: a "check" is a shell command you save (like `pytest` or
# `npm test`) that proves the project works. Checks live in the workspace's
# aicompany.json. Running one streams its output live (as check_output events) and ends
# with an exit code the UI turns into a green/red badge.
#
# WHY the sanitized env + one-at-a-time lock: checks run real shell commands, so they get
# the SAME key-stripped environment as the terminal (app/shell_env.py). And we run one
# check at a time per workspace — this is verification, not a job queue, so a simple
# asyncio.Lock is exactly enough.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from app.events import event_bus
from app.shell_env import sanitized_env

logger = logging.getLogger("aicompany.checks")

CHECKS_FILENAME = "aicompany.json"

# One lock per workspace id, so two runs on the same workspace queue instead of overlap.
_locks: dict[str, asyncio.Lock] = {}


def read_checks(path: str) -> list[dict]:
    """Return the saved checks from a workspace's aicompany.json (empty list if none)."""
    checks_file = Path(path) / CHECKS_FILENAME
    if not checks_file.exists():
        return []
    try:
        return json.loads(checks_file.read_text()).get("checks", [])
    except (json.JSONDecodeError, OSError):
        return []


def write_checks(path: str, checks: list[dict]) -> None:
    """Persist the checks list back to aicompany.json."""
    checks_file = Path(path) / CHECKS_FILENAME
    checks_file.write_text(json.dumps({"checks": checks}, indent=2), encoding="utf-8")


async def run_check(workspace_id: str, path: str, check_id: str) -> None:
    """Run one saved check, streaming its output and finishing with an exit code.

    Emits check_started, then check_output per line, then check_finished. Any failure to
    launch becomes a captured line + a non-zero exit — the runner never raises to caller.
    """
    check = next((c for c in read_checks(path) if c.get("id") == check_id), None)
    if check is None:
        return  # nothing to run; the UI simply won't see a started/finished pair
    command = check["command"]

    lock = _locks.setdefault(workspace_id, asyncio.Lock())
    async with lock:  # one check at a time per workspace
        event_bus.publish(
            "check_started",
            {"workspace_id": workspace_id, "check_id": check_id, "command": command},
        )
        started = time.monotonic()
        exit_code = 1
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=path,
                env=sanitized_env(path),  # ⚠️ same key-stripped env as the terminal
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # merge so output stays in order
            )
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").rstrip("\n")
                event_bus.publish(
                    "check_output", {"check_id": check_id, "stream": "stdout", "line": line}
                )
            exit_code = await process.wait()
        except Exception as error:  # noqa: BLE001 — a bad command must not crash the server
            logger.warning("check %s failed to run: %s", check_id, error)
            event_bus.publish(
                "check_output",
                {"check_id": check_id, "stream": "stderr", "line": f"[failed to run: {error}]"},
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        event_bus.publish(
            "check_finished",
            {"check_id": check_id, "exit_code": exit_code, "duration_ms": duration_ms},
        )
