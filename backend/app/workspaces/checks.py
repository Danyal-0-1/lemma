# ─────────────────────────────────────────────────────────────────────────────
# checks.py — bounded, explicitly enabled verification commands.
# READING ORDER: backend #42
#
# Checks are trusted-human tools, not an agent capability. The API keeps execution
# disabled by default; this module adds defense in depth: typed definitions, no
# implicit shell, a minimal environment, wall/output limits, and process-group cleanup.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import signal
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from app.events import event_bus
from app.shell_env import sanitized_env

logger = logging.getLogger("aicompany.checks")

CHECKS_FILENAME = "aicompany.json"
MAX_CHECKS = 30
MAX_COMMAND_CHARS = 2_000
MAX_OUTPUT_BYTES = 1_000_000
MAX_OUTPUT_LINES = 4_000
CHECK_TIMEOUT_SECONDS = 120

CheckId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[\w.-]+$"),
]


class CheckDefinition(BaseModel):
    """One saved command shown verbatim to the user before explicit execution."""

    model_config = ConfigDict(extra="forbid")

    id: CheckId
    name: str = Field(min_length=1, max_length=160)
    command: str = Field(min_length=1, max_length=MAX_COMMAND_CHARS)


_check_list = TypeAdapter(list[CheckDefinition])
_locks: dict[str, asyncio.Lock] = {}


def _validated(raw: object) -> list[CheckDefinition]:
    checks = _check_list.validate_python(raw)
    if len(checks) > MAX_CHECKS:
        raise ValueError(f"at most {MAX_CHECKS} checks may be saved")
    ids = [check.id for check in checks]
    if len(ids) != len(set(ids)):
        raise ValueError("check ids must be unique")
    return checks


def read_checks(path: str) -> list[dict[str, str]]:
    """Return validated checks, ignoring corrupt or symlinked executable config."""
    checks_file = Path(path).resolve() / CHECKS_FILENAME
    if not checks_file.exists() or checks_file.is_symlink():
        return []
    try:
        payload = json.loads(checks_file.read_text(encoding="utf-8"))
        return [check.model_dump() for check in _validated(payload.get("checks", []))]
    except (ValueError, json.JSONDecodeError, OSError):
        logger.warning("ignoring invalid checks file at %s", checks_file)
        return []


def write_checks(path: str, checks: list[dict]) -> None:
    """Validate then atomically replace checks without following a target symlink."""
    normalized = _validated(checks)
    root = Path(path).resolve(strict=True)
    destination = root / CHECKS_FILENAME
    temporary = root / f".{CHECKS_FILENAME}.{uuid4().hex}.tmp"
    data = json.dumps({"checks": [check.model_dump() for check in normalized]}, indent=2)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _argv(command: str) -> list[str]:
    """Parse a command into argv; shell operators have no special meaning."""
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as error:
        raise ValueError(f"invalid command quoting: {error}") from error
    if not argv or len(argv) > 100 or any("\x00" in item for item in argv):
        raise ValueError("command has an invalid argument list")
    return argv


async def _stop_process_group(process: asyncio.subprocess.Process) -> None:
    """Terminate the complete check process group, escalating after a short grace."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def run_check(workspace_id: str, path: str, check_id: str) -> None:
    """Execute one validated argv command with hard time and output limits."""
    check = next((item for item in read_checks(path) if item["id"] == check_id), None)
    if check is None:
        return

    lock = _locks.setdefault(workspace_id, asyncio.Lock())
    async with lock:
        base = {"workspace_id": workspace_id, "check_id": check_id}
        event_bus.publish("check_started", {**base, "command": check["command"]})
        started = time.monotonic()
        exit_code = 1
        process: asyncio.subprocess.Process | None = None
        output_bytes = 0
        output_lines = 0
        limit_reason: str | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *_argv(check["command"]),
                cwd=path,
                env=sanitized_env(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert process.stdout is not None

            async def consume() -> None:
                nonlocal output_bytes, output_lines, limit_reason
                async for raw_line in process.stdout:
                    output_bytes += len(raw_line)
                    output_lines += 1
                    if output_bytes > MAX_OUTPUT_BYTES or output_lines > MAX_OUTPUT_LINES:
                        limit_reason = "output limit reached; process stopped"
                        await _stop_process_group(process)
                        return
                    line = raw_line.decode(errors="replace").rstrip("\r\n")
                    event_bus.publish(
                        "check_output",
                        {**base, "stream": "stdout", "line": line},
                    )
                await process.wait()

            try:
                await asyncio.wait_for(consume(), timeout=CHECK_TIMEOUT_SECONDS)
            except TimeoutError:
                limit_reason = f"timed out after {CHECK_TIMEOUT_SECONDS} seconds"
                await _stop_process_group(process)

            if limit_reason:
                event_bus.publish(
                    "check_output",
                    {**base, "stream": "stderr", "line": f"[{limit_reason}]"},
                )
                exit_code = 124 if "timed out" in limit_reason else 125
            else:
                exit_code = process.returncode if process.returncode is not None else 1
        except (OSError, ValueError) as error:
            logger.warning("check %s failed to run: %s", check_id, error)
            event_bus.publish(
                "check_output",
                {**base, "stream": "stderr", "line": f"[failed to run: {error}]"},
            )
        finally:
            if process is not None and process.returncode is None:
                await _stop_process_group(process)

        duration_ms = int((time.monotonic() - started) * 1000)
        event_bus.publish(
            "check_finished",
            {**base, "exit_code": exit_code, "duration_ms": duration_ms},
        )
