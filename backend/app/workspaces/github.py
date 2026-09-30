"""Safe GitHub CLI discovery and account-status reporting.

Lemma never asks for, reads, or persists a GitHub token.  HTTPS Git operations may
delegate credential lookup to an already authenticated ``gh`` installation, while SSH
continues to use the operator's normal keys.  The only account command used here omits
``--show-token`` and its output is parsed into a deliberately small public shape.
"""

from __future__ import annotations

import json
import os
import select
import shlex
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

from app.shell_env import sanitized_env
from app.workspaces.gitutil import GitResult

GITHUB_HOST = "github.com"
GH_TIMEOUT_SECONDS = 8
MAX_GH_OUTPUT_BYTES = 64_000


def _find_gh_executable() -> str | None:
    """Return one canonical executable path, never a shell command."""
    candidates = [
        "/usr/bin/gh",
        "/usr/local/bin/gh",
        "/snap/bin/gh",
        "/opt/homebrew/bin/gh",
    ]
    discovered = shutil.which("gh")
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        try:
            resolved = Path(candidate).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        value = str(resolved)
        if (
            resolved.is_file()
            and os.access(resolved, os.X_OK)
            and not any(ord(character) < 32 for character in value)
        ):
            return value
    return None


GH_EXECUTABLE = _find_gh_executable()


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


def _run_gh(args: list[str], cwd: Path) -> GitResult:
    """Run the fixed GitHub CLI executable with no prompts and bounded output."""
    if GH_EXECUTABLE is None:
        return GitResult(127, "GitHub CLI is not installed")
    env = sanitized_env(str(cwd))
    env.update(
        {
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_TELEMETRY": "0",
            "NO_COLOR": "1",
        }
    )
    # Respect an explicitly configured gh/XDG directory without widening the shared
    # subprocess allowlist. These values are paths, not tokens, and remain scoped to gh.
    for key in ("GH_CONFIG_DIR", "XDG_CONFIG_HOME"):
        value = os.environ.get(key)
        if (
            value
            and Path(value).is_absolute()
            and len(value) <= 4_096
            and not any(ord(character) < 32 for character in value)
        ):
            env[key] = value
    try:
        process = subprocess.Popen(
            [GH_EXECUTABLE, *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    except OSError as error:
        return GitResult(127, f"GitHub CLI is unavailable: {error.strerror or 'error'}")

    assert process.stdout is not None
    chunks: list[bytes] = []
    received = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + GH_TIMEOUT_SECONDS
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
            chunk = os.read(process.stdout.fileno(), min(16 * 1024, MAX_GH_OUTPUT_BYTES + 1))
            if not chunk:
                break
            remaining_capacity = MAX_GH_OUTPUT_BYTES - received
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
        process.returncode if process.returncode is not None else -1,
        b"".join(chunks).decode(errors="replace"),
        truncated=truncated,
        timed_out=timed_out,
    )


def _storage_kind(token_source: object) -> str:
    """Classify credential storage without returning its filesystem location."""
    if not isinstance(token_source, str):
        return "unknown"
    lowered = token_source.lower()
    if "keyring" in lowered or "keychain" in lowered or "credential" in lowered:
        return "system_credential_store"
    if lowered.endswith("_token"):
        return "environment"
    if "/" in token_source or "\\" in token_source or lowered.endswith(('.yml', '.yaml')):
        return "github_cli_config"
    return "github_cli"


def github_connection_status(cwd: str | None = None) -> dict[str, object]:
    """Return the active github.com account without ever requesting its token."""
    if GH_EXECUTABLE is None:
        return {
            "cli_installed": False,
            "authenticated": False,
            "login": None,
            "git_protocol": None,
            "credential_storage": None,
            "message": "Install GitHub CLI, then run `gh auth login` in the terminal.",
        }

    directory = Path(cwd).resolve(strict=True) if cwd else Path.home()
    result = _run_gh(
        [
            "auth",
            "status",
            "--active",
            "--hostname",
            GITHUB_HOST,
            "--json",
            "hosts",
        ],
        directory,
    )
    if result.timed_out:
        message = "GitHub authentication check timed out."
    elif result.truncated:
        message = "GitHub CLI returned too much data."
    elif result.returncode != 0:
        message = "GitHub CLI could not read the local authentication state."
    else:
        message = "Run `gh auth login` in the terminal to connect GitHub."

    try:
        document = (
            json.loads(result.output)
            if not result.timed_out and not result.truncated
            else {}
        )
    except (json.JSONDecodeError, TypeError):
        document = {}
    hosts = document.get("hosts", {}) if isinstance(document, dict) else {}
    accounts = hosts.get(GITHUB_HOST, []) if isinstance(hosts, dict) else []
    entries = (
        [entry for entry in accounts if isinstance(entry, dict)]
        if isinstance(accounts, list)
        else []
    )
    active = next((entry for entry in entries if entry.get("active") is True), None)
    if active is None and entries:
        active = entries[0]

    authenticated = bool(active and active.get("state") == "success")
    login = active.get("login") if active else None
    if not isinstance(login, str) or not login or len(login) > 100 or any(
        ord(character) < 32 for character in login
    ):
        login = None
    protocol = active.get("gitProtocol") if active else None
    if protocol not in {"ssh", "https"}:
        protocol = None
    storage = _storage_kind(active.get("tokenSource")) if active else None
    if authenticated:
        message = f"Connected to GitHub as {login}." if login else "Connected to GitHub."
    elif active and active.get("state") in {"error", "timeout"}:
        message = "The saved GitHub authentication is unavailable or expired."

    return {
        "cli_installed": True,
        "authenticated": authenticated,
        "login": login,
        "git_protocol": protocol,
        "credential_storage": storage,
        "message": message,
    }


def https_credential_helper_args() -> list[str]:
    """Build explicit Git config args that broker HTTPS auth through ``gh``.

    Git invokes credential helpers through a shell.  The executable is a canonical,
    pre-discovered file path and is shell-quoted as one token; no user input enters the
    helper command.  The initial empty helper also prevents fallback to repo config.
    """
    if GH_EXECUTABLE is None:
        raise RuntimeError("GitHub CLI is not installed")
    helper = f"!{shlex.quote(GH_EXECUTABLE)} auth git-credential"
    return [
        "-c",
        "credential.helper=",
        "-c",
        f"credential.https://{GITHUB_HOST}.helper={helper}",
    ]


def ssh_agent_environment() -> dict[str, str]:
    """Forward only a real local SSH-agent socket to a GitHub SSH push."""
    value = os.environ.get("SSH_AUTH_SOCK", "")
    if (
        not value
        or len(value) > 4_096
        or not Path(value).is_absolute()
        or any(ord(character) < 32 for character in value)
    ):
        return {}
    try:
        mode = os.stat(value).st_mode
    except OSError:
        return {}
    return {"SSH_AUTH_SOCK": value} if stat.S_ISSOCK(mode) else {}
