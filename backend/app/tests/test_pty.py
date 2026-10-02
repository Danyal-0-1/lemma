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
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.terminal import pty_service

TRUSTED_ORIGIN = "http://127.0.0.1:5173"


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


def test_shell_resolution_prefers_valid_configured_zsh(tmp_path, monkeypatch) -> None:
    """A valid user-selected zsh is retained rather than replaced by a fallback."""
    zsh = tmp_path / "zsh"
    zsh.write_text("#!/bin/sh\n", encoding="utf-8")
    zsh.chmod(0o700)
    monkeypatch.setenv("SHELL", str(zsh))

    assert pty_service._resolve_shell() == str(zsh)
    assert pty_service._shell_argv(str(zsh)) == [str(zsh), "-f"]


def test_invalid_configured_shell_falls_back_to_bash(tmp_path, monkeypatch) -> None:
    """An unsupported or missing $SHELL cannot create a silently blank terminal."""
    bash = tmp_path / "bash"
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    bash.chmod(0o700)
    monkeypatch.setenv("SHELL", "/private/not-a-shell/fish")
    monkeypatch.setattr(pty_service, "_default_shell_candidates", lambda: (str(bash),))

    assert pty_service._resolve_shell() == str(bash)
    assert pty_service._shell_argv(str(bash)) == [
        str(bash),
        "--noprofile",
        "--norc",
    ]


def test_no_valid_shell_has_actionable_sanitized_error(monkeypatch) -> None:
    """Shell validation reports recovery guidance without echoing the bad local path."""
    private_path = "/private/users/alice/secret-shell"
    monkeypatch.setenv("SHELL", private_path)
    monkeypatch.setattr(pty_service, "_default_shell_candidates", tuple)

    with pytest.raises(pty_service.TerminalSpawnError) as raised:
        pty_service._resolve_shell()

    assert "Install bash or zsh" in str(raised.value)
    assert private_path not in str(raised.value)


def test_pty_allocation_failure_is_sanitized(tmp_path, monkeypatch) -> None:
    """Raw OS details never escape when the host cannot allocate a PTY."""
    monkeypatch.setattr(pty_service, "_resolve_shell", lambda: "/bin/bash")

    def fail_fork() -> tuple[int, int]:
        raise OSError("secret device path and host details")

    monkeypatch.setattr(pty_service.pty, "fork", fail_fork)
    with pytest.raises(pty_service.TerminalSpawnError) as raised:
        pty_service.create_terminal(str(tmp_path))

    assert raised.value.reason == "pty_unavailable"
    assert "secret device path" not in str(raised.value)


def test_shell_exec_failure_is_reported_before_terminal_registration(
    tmp_path, monkeypatch
) -> None:
    """An executable-looking but broken shell cannot become a blank live terminal."""
    broken_bash = tmp_path / "bash"
    broken_bash.write_bytes(b"not a valid executable")
    broken_bash.chmod(0o700)
    monkeypatch.setenv("SHELL", str(broken_bash))
    before = set(pty_service._terminals)

    with pytest.raises(pty_service.TerminalSpawnError) as raised:
        pty_service.create_terminal(str(tmp_path))

    assert raised.value.reason == "shell_start_failed"
    assert set(pty_service._terminals) == before


def test_terminal_route_returns_safe_spawn_error(monkeypatch) -> None:
    """The POST route turns startup failures into a visible, retryable HTTP response."""
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(enable_host_execution=True),
    )
    monkeypatch.setattr(
        main_module.manager,
        "get_workspace",
        lambda _workspace_id: SimpleNamespace(path="/private/sensitive/workspace"),
    )
    monkeypatch.setattr(
        main_module.manager,
        "validated_workspace_path",
        lambda workspace: workspace.path,
    )

    def fail_create(_path: str) -> str:
        raise pty_service.TerminalSpawnError("shell_start_failed")

    monkeypatch.setattr(main_module, "create_terminal", fail_create)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/terminals",
            json={"workspace_id": "workspace-1"},
            headers={"Origin": TRUSTED_ORIGIN},
        )
    finally:
        client.close()

    assert response.status_code == 503
    assert "bash or zsh installation" in response.json()["detail"]
    assert "sensitive" not in response.text
