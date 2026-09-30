# ─────────────────────────────────────────────────────────────────────────────
# gitutil.py — tiny wrappers for running git in a workspace.
# READING ORDER: backend #39
#
# WHAT THIS FILE DOES: two helpers. git_run() runs a git command and RAISES if it fails
# (for actions like init/commit we need to succeed). git_output() runs a read-only query
# and returns its stdout, IGNORING the exit code (a diff/show that "fails" — e.g. a file
# not in HEAD — is normal and just means "no output").
#
# WHY split them: mixing "must succeed" with "failure is fine" in one helper hides bugs.
# Naming the two intents keeps every call site honest.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.shell_env import sanitized_env

GIT_TIMEOUT_SECONDS = 15
MAX_GIT_OUTPUT_BYTES = 4_000_000


def _find_git_executable() -> str:
    """Prefer the real macOS Git binary over the ``/usr/bin/git`` xcrun shim."""
    candidates: list[str] = []
    if sys.platform == "darwin":
        candidates.extend(
            [
                "/Library/Developer/CommandLineTools/usr/bin/git",
                "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
            ]
        )
    discovered = shutil.which("git")
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return "git"


GIT_EXECUTABLE = _find_git_executable()


@dataclass(frozen=True)
class GitResult:
    """A bounded Git process result used by the source-control API."""

    returncode: int
    output: str
    truncated: bool = False
    timed_out: bool = False


def _command(args: list[str], cwd: Path) -> list[str]:
    """Build Git argv with dangerous config-driven execution paths disabled."""
    return [
        GIT_EXECUTABLE,
        "--no-pager",
        "--literal-pathspecs",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "color.ui=false",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "credential.helper=",
        "-c",
        (
            "core.sshCommand=ssh -F /dev/null -oBatchMode=yes "
            "-oPermitLocalCommand=no -oProxyCommand=none -oClearAllForwardings=yes"
        ),
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "protocol.ssh.allow=always",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "http.extraHeader=",
        "-c",
        "submodule.recurse=false",
        "-C",
        str(cwd),
        *args,
    ]


def _environment(cwd: Path) -> dict[str, str]:
    """Give Git no backend secrets, interactive prompts, or executable global config."""
    env = sanitized_env(str(cwd))
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
    )
    return env


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def git_run(args: list[str], cwd: Path) -> None:
    """Run a git command that must succeed (raises CalledProcessError otherwise)."""
    subprocess.run(
        _command(args, cwd),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_environment(cwd),
    )


def git_output(args: list[str], cwd: Path) -> str:
    """Run a read-only git query and return its stdout, ignoring a non-zero exit.

    Exists for `diff` / `status` / `show` where a non-zero exit is a normal outcome
    (e.g. `git show HEAD:new_file` fails because the file isn't in HEAD yet).
    """
    process = subprocess.Popen(
        _command(args, cwd),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_environment(cwd),
        start_new_session=True,
    )
    assert process.stdout is not None
    chunks: list[bytes] = []
    received = 0
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    try:
        while received <= MAX_GIT_OUTPUT_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                break
            chunk = os.read(
                process.stdout.fileno(),
                min(64 * 1024, MAX_GIT_OUTPUT_BYTES + 1 - received),
            )
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        remaining = max(0.01, deadline - time.monotonic())
        if received <= MAX_GIT_OUTPUT_BYTES:
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
    finally:
        _stop(process)
        process.stdout.close()
    return b"".join(chunks)[:MAX_GIT_OUTPUT_BYTES].decode(errors="replace")


def git_capture(
    args: list[str],
    cwd: Path,
    *,
    timeout: float = GIT_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    extra_env: dict[str, str] | None = None,
) -> GitResult:
    """Run fixed-argv Git and capture combined output with hard time/size bounds."""
    env = _environment(cwd)
    if extra_env:
        env.update(extra_env)
    try:
        process = subprocess.Popen(
            _command(args, cwd),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    except OSError as error:
        return GitResult(returncode=127, output=f"Git is unavailable: {error.strerror or 'error'}")

    assert process.stdout is not None
    chunks: list[bytes] = []
    received = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = process.poll() is None
                break
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                timed_out = process.poll() is None
                break
            chunk = os.read(process.stdout.fileno(), min(64 * 1024, max_output_bytes + 1))
            if not chunk:
                break
            remaining_capacity = max_output_bytes - received
            if len(chunk) > remaining_capacity:
                if remaining_capacity > 0:
                    chunks.append(chunk[:remaining_capacity])
                    received += remaining_capacity
                truncated = True
                break
            chunks.append(chunk)
            received += len(chunk)

        if not truncated and not timed_out:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        _stop(process)
        process.stdout.close()

    return GitResult(
        returncode=process.returncode if process.returncode is not None else -1,
        output=b"".join(chunks).decode(errors="replace"),
        truncated=truncated,
        timed_out=timed_out,
    )
