# ─────────────────────────────────────────────────────────────────────────────
# pty_service.py — the embedded terminal: a real shell running inside a workspace.
# READING ORDER: backend #34  ← RETYPE THIS (M5)
#
# WHAT THIS FILE DOES:
#   Spawns the user's shell attached to a pseudo-terminal (PTY), so a full interactive
#   program like `claude` or `vim` runs correctly (arrow keys, Ctrl-C, colors). It
#   pumps bytes both ways between that shell and a WebSocket, and handles resize.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  BILLING SAFETY: the env we spawn the shell with comes from               ║
# ║  app/shell_env.py::sanitized_env(), which builds a minimal allowlist.          ║
# ║  Provider keys and other credentials are never inherited by the shell.         ║
# ║  That's what prevents accidental metered API use. Read that file.              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# WHY pty.fork (not a plain subprocess): a PTY makes the shell believe it's talking to
#   a real terminal. pty.fork wires the child's stdin/out/err to the slave side and
#   makes it the controlling terminal (job control works). We keep the master side to
#   read output and write input.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import secrets
import select
import signal
import struct
import sys
import termios
import threading
import time
from pathlib import Path

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.shell_env import sanitized_env

logger = logging.getLogger("aicompany.pty")

# Registry of live terminals so a /pty socket can find its shell by id.
_terminals: dict[str, PtyTerminal] = {}
_terminals_lock = threading.Lock()
CLAIM_TTL_SECONDS = 30
MAX_OUTPUT_CHUNKS = 256
MAX_INPUT_FRAME_BYTES = 64 * 1024
MAX_CONTROL_FRAME_CHARS = 4_096
SHELL_START_TIMEOUT_SECONDS = 2.0

_SPAWN_ERROR_MESSAGES = {
    "workspace_unavailable": (
        "The workspace is unavailable. Reopen or restore it, then try the terminal again."
    ),
    "shell_unavailable": (
        "No supported interactive shell is available. Install bash or zsh, then restart Lemma."
    ),
    "pty_unavailable": (
        "The terminal could not start. Check that this macOS or Linux system supports PTYs, "
        "then restart Lemma."
    ),
    "shell_start_failed": (
        "The selected shell could not start. Check your bash or zsh installation, then retry."
    ),
}


class TerminalSpawnError(RuntimeError):
    """A terminal startup failure whose message is safe to return to the browser.

    Callers choose a fixed reason instead of interpolating an ``OSError``. This keeps
    credentials and local filesystem paths out of API responses while still telling
    the operator how to recover.
    """

    def __init__(self, reason: str) -> None:
        try:
            message = _SPAWN_ERROR_MESSAGES[reason]
        except KeyError as error:  # pragma: no cover - internal programming error
            raise ValueError("unknown terminal spawn error") from error
        self.reason = reason
        super().__init__(message)


def _default_shell_candidates() -> tuple[str, ...]:
    """Return common shell locations in the platform's usual preference order."""
    if sys.platform == "darwin":
        return ("/bin/zsh", "/bin/bash", "/usr/bin/zsh", "/usr/bin/bash")
    return ("/bin/bash", "/usr/bin/bash", "/bin/zsh", "/usr/bin/zsh")


def _is_supported_shell(path: str) -> bool:
    """Accept only an absolute, executable bash/zsh file (including safe symlinks)."""
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.name not in {"bash", "zsh"}:
        return False
    try:
        return candidate.is_file() and os.access(candidate, os.X_OK)
    except OSError:
        return False


def _resolve_shell() -> str:
    """Resolve ``$SHELL`` with portable bash/zsh fallbacks for macOS and Linux."""
    configured = os.environ.get("SHELL", "").strip()
    if configured and _is_supported_shell(configured):
        return configured
    if configured:
        # Deliberately do not log the configured value: environment values and local
        # filesystem layout do not belong in logs or browser-visible errors.
        logger.warning("configured SHELL is unavailable or unsupported; using a fallback")

    for candidate in _default_shell_candidates():
        if _is_supported_shell(candidate):
            return candidate
    raise TerminalSpawnError("shell_unavailable")


def _shell_argv(shell: str) -> list[str]:
    """Start a clean interactive shell without profiles that could restore secrets."""
    if os.path.basename(shell) == "zsh":
        return [shell, "-f"]
    return [shell, "--noprofile", "--norc"]


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _reap_failed_spawn(pid: int, master_fd: int) -> None:
    """Best-effort cleanup for a child that failed before terminal registration."""
    _close_fd(master_fd)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Tell the PTY its window size, so full-screen programs lay out correctly."""
    # TIOCSWINSZ expects four unsigned shorts: rows, cols, and (unused) pixel sizes.
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


class PtyTerminal:
    """One shell attached to a PTY: its child pid and the master fd we talk over."""

    def __init__(self, terminal_id: str, pid: int, master_fd: int, path: str) -> None:
        self.id = terminal_id
        self.pid = pid
        self.master_fd = master_fd
        self.path = path
        self.claim_deadline = time.monotonic() + CLAIM_TTL_SECONDS
        self.expiry_timer: threading.Timer | None = None

    def write(self, data: bytes) -> None:
        """Send bytes (the user's keystrokes) into the shell."""
        os.write(self.master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY window."""
        _set_winsize(self.master_fd, max(2, min(rows, 500)), max(2, min(cols, 500)))

    def close(self) -> None:
        """Close the PTY and REAP the child, so no zombie/hung process is left behind.

        macOS-safe: closing the master side sends SIGHUP to the shell's process group;
        we then waitpid to reap it, escalating to SIGKILL if it lingers. The strict
        try/except around each fd/pid call keeps a half-dead terminal from raising.
        """
        if self.expiry_timer is not None:
            self.expiry_timer.cancel()
        with _terminals_lock:
            if _terminals.get(self.id) is self:
                _terminals.pop(self.id, None)

        # Terminate the PTY's process group, not just the shell process. A child that
        # ignored SIGHUP must not survive after the browser disconnects.
        try:
            os.killpg(self.pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass

        # Give the shell up to ~1s to exit from the SIGHUP that closing the master sent.
        deadline = time.time() + 1.0
        while time.time() < deadline:
            try:
                reaped, _ = os.waitpid(self.pid, os.WNOHANG)
                if reaped == self.pid:
                    return
            except ChildProcessError:
                return  # already reaped elsewhere
            time.sleep(0.02)

        # Still alive → force it, then reap so it can't become a zombie.
        try:
            os.killpg(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def create_terminal(workspace_path: str) -> str:
    """Fork a shell attached to a new PTY, running in `workspace_path`. Returns its id.

    Exists so the /pty socket has a shell to connect to. The child execs the user's
    $SHELL with the SANITIZED env (see the billing warning above).
    """
    workspace = Path(workspace_path)
    try:
        workspace_available = workspace.is_dir() and os.access(workspace, os.R_OK | os.X_OK)
    except OSError:
        workspace_available = False
    if not workspace_available:
        raise TerminalSpawnError("workspace_unavailable")

    terminal_id = f"pty_{secrets.token_urlsafe(32)}"
    shell = _resolve_shell()
    env = sanitized_env(workspace_path)  # ⚠️ allowlists child env — see app/shell_env.py
    # When an invalid configured shell falls back, children must see the shell that
    # actually started rather than the stale value from the parent environment.
    env["SHELL"] = shell

    # The close-on-exec pipe lets the parent distinguish a successful exec from the
    # old failure mode where the child silently exited 127 and the browser stayed blank.
    try:
        error_read_fd, error_write_fd = os.pipe()
    except OSError as error:
        logger.warning("could not allocate terminal startup pipe: %s", type(error).__name__)
        raise TerminalSpawnError("pty_unavailable") from error

    # pty.fork() forks; in the CHILD it wires stdio to the PTY and returns pid 0.
    try:
        pid, master_fd = pty.fork()
    except OSError as error:
        _close_fd(error_read_fd)
        _close_fd(error_write_fd)
        logger.warning("could not allocate PTY: %s", type(error).__name__)
        raise TerminalSpawnError("pty_unavailable") from error
    if pid == 0:
        # ---- child process ----
        _close_fd(error_read_fd)
        try:
            os.chdir(workspace_path)
            os.execvpe(shell, _shell_argv(shell), env)  # replaces child with shell
        except BaseException:  # noqa: BLE001 — child must never fall through to app code
            try:
                os.write(error_write_fd, b"failed")
            except OSError:
                pass
            os._exit(127)

    # ---- parent process ----
    _close_fd(error_write_fd)
    try:
        ready, _, _ = select.select(
            [error_read_fd],
            [],
            [],
            SHELL_START_TIMEOUT_SECONDS,
        )
        startup_error = os.read(error_read_fd, 16) if ready else b"timeout"
    except OSError:
        startup_error = b"failed"
    finally:
        _close_fd(error_read_fd)
    if startup_error:
        _reap_failed_spawn(pid, master_fd)
        logger.warning("terminal shell failed before startup completed")
        raise TerminalSpawnError("shell_start_failed")

    # Non-blocking so our reader never stalls the event loop when there's no output.
    try:
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    except OSError as error:
        _reap_failed_spawn(pid, master_fd)
        logger.warning("could not configure PTY: %s", type(error).__name__)
        raise TerminalSpawnError("pty_unavailable") from error

    terminal = PtyTerminal(terminal_id, pid, master_fd, workspace_path)
    def expire_unclaimed() -> None:
        with _terminals_lock:
            stale = _terminals.pop(terminal_id, None)
        if stale is terminal:
            logger.warning("reaping unclaimed terminal %s", terminal_id)
            stale.close()

    terminal.expiry_timer = threading.Timer(CLAIM_TTL_SECONDS, expire_unclaimed)
    terminal.expiry_timer.daemon = True
    with _terminals_lock:
        _terminals[terminal_id] = terminal
    terminal.expiry_timer.start()
    logger.info("spawned terminal %s (%s) in %s", terminal_id, shell, workspace_path)
    return terminal_id


def _handle_control(terminal: PtyTerminal, text: str) -> None:
    """Handle a JSON control message from the client (currently just resize)."""
    if len(text) > MAX_CONTROL_FRAME_CHARS:
        return
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return
    if message.get("type") == "resize":
        try:
            terminal.resize(int(message.get("rows", 24)), int(message.get("cols", 80)))
        except (TypeError, ValueError, OverflowError):
            return


async def connect_pty(websocket: WebSocket, terminal_id: str) -> None:
    """Serve one /pty connection: pump PTY output → socket and socket input → PTY.

    Exists as the terminal's transport. Output is read off the master fd via the event
    loop's reader and queued so frames stay ordered; input arrives as binary frames
    (keystrokes) or text frames (resize control). On disconnect we always reap the shell.
    """
    # The capability is one-use: remove it atomically before accepting the socket.
    with _terminals_lock:
        terminal = _terminals.pop(terminal_id, None)
    if terminal is None:
        await websocket.close(code=1008)
        return
    if terminal.expiry_timer is not None:
        terminal.expiry_timer.cancel()
    if time.monotonic() > terminal.claim_deadline:
        await asyncio.to_thread(terminal.close)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=MAX_OUTPUT_CHUNKS)
    overflowed = False

    def on_readable() -> None:
        # Called by the event loop when the shell has output (or has exited).
        try:
            data = os.read(terminal.master_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return  # spurious wakeup; nothing to read yet
        except OSError:
            data = b""  # fd closed / shell gone → treat as EOF
        nonlocal overflowed
        try:
            output.put_nowait(data if data else None)
        except asyncio.QueueFull:
            if not overflowed:
                overflowed = True
                loop.remove_reader(terminal.master_fd)
                asyncio.create_task(asyncio.to_thread(terminal.close))
                asyncio.create_task(websocket.close(code=1013, reason="terminal output overflow"))

    loop.add_reader(terminal.master_fd, on_readable)

    async def pump_output() -> None:
        # Drain the queue in order and forward to the browser; None means the shell ended.
        while True:
            chunk = await output.get()
            if chunk is None:
                break
            await websocket.send_bytes(chunk)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()

    sender = asyncio.create_task(pump_output())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                if len(data) > MAX_INPUT_FRAME_BYTES:
                    await websocket.close(code=1009, reason="terminal input frame too large")
                    break
                terminal.write(data)  # keystrokes
            elif (text := message.get("text")) is not None:
                _handle_control(terminal, text)  # resize
    except WebSocketDisconnect:
        pass
    finally:
        try:
            loop.remove_reader(terminal.master_fd)
        except (OSError, ValueError):
            pass
        try:
            output.put_nowait(None)  # unblock the sender
        except asyncio.QueueFull:
            pass
        sender.cancel()
        # Reap off the event loop (it does short blocking waits).
        await asyncio.to_thread(terminal.close)
