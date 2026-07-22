# ─────────────────────────────────────────────────────────────────────────────
# test_pty.py — prove the terminal strips API keys (the billing-safety guarantee).
# READING ORDER: backend #37
#
# This is the most important test in the app. We deliberately put a fake
# ANTHROPIC_API_KEY in the environment, spawn a shell through the PTY, and confirm the
# key is EMPTY inside that shell. If this ever fails, a `claude` run in the terminal
# could silently switch to metered API billing — the exact bug this code prevents.
# ─────────────────────────────────────────────────────────────────────────────

import os
import select
import time

from app.terminal import pty_service


def _read_for(master_fd: int, seconds: float) -> str:
    """Read whatever the shell produces within `seconds`, as text (best effort)."""
    collected = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([master_fd], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        collected.extend(chunk)
    return collected.decode(errors="replace")


def test_terminal_strips_api_keys(tmp_path, monkeypatch) -> None:
    """A spawned shell sees an EMPTY ANTHROPIC_API_KEY even when the app process has one."""
    # Simulate the dangerous situation: the key is present in the app's environment.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leaked-secret-should-not-appear")
    monkeypatch.setenv("SHELL", "/bin/bash")

    terminal_id = pty_service.create_terminal(str(tmp_path))
    terminal = pty_service._terminals[terminal_id]
    try:
        # A uniquely-delimited probe so we can tell the RESULT from the echoed command.
        terminal.write(b"echo VAL:[$ANTHROPIC_API_KEY]:END\n")
        output = _read_for(terminal.master_fd, 2.0)

        # The expansion is empty → "VAL:[]:END". The secret must never appear.
        assert "VAL:[]:END" in output, output
        assert "leaked-secret-should-not-appear" not in output
    finally:
        terminal.close()


def test_terminal_runs_a_command(tmp_path, monkeypatch) -> None:
    """A basic sanity check that the shell actually executes what we type."""
    monkeypatch.setenv("SHELL", "/bin/bash")
    terminal_id = pty_service.create_terminal(str(tmp_path))
    terminal = pty_service._terminals[terminal_id]
    try:
        terminal.write(b"echo hello-from-pty\n")
        output = _read_for(terminal.master_fd, 2.0)
        assert "hello-from-pty" in output
    finally:
        terminal.close()
