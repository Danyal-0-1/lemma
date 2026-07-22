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
# ║  app/shell_env.py::sanitized_env(), which STRIPS ANTHROPIC_API_KEY /          ║
# ║  OPENAI_API_KEY. That's what makes a `claude` session here use your           ║
# ║  SUBSCRIPTION, not per-token API billing. Read that file.                     ║
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
import signal
import struct
import termios
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.shell_env import sanitized_env

logger = logging.getLogger("aicompany.pty")

# Registry of live terminals so a /pty socket can find its shell by id.
_terminals: dict[str, PtyTerminal] = {}


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

    def write(self, data: bytes) -> None:
        """Send bytes (the user's keystrokes) into the shell."""
        os.write(self.master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY window."""
        _set_winsize(self.master_fd, rows, cols)

    def close(self) -> None:
        """Close the PTY and REAP the child, so no zombie/hung process is left behind.

        macOS-safe: closing the master side sends SIGHUP to the shell's process group;
        we then waitpid to reap it, escalating to SIGKILL if it lingers. The strict
        try/except around each fd/pid call keeps a half-dead terminal from raising.
        """
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
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def create_terminal(workspace_path: str) -> str:
    """Fork a shell attached to a new PTY, running in `workspace_path`. Returns its id.

    Exists so the /pty socket has a shell to connect to. The child execs the user's
    $SHELL with the SANITIZED env (see the billing warning above).
    """
    terminal_id = f"pty_{os.urandom(4).hex()}"
    shell = os.environ.get("SHELL", "/bin/bash")
    env = sanitized_env(workspace_path)  # ⚠️ strips API keys — see app/shell_env.py

    # pty.fork() forks; in the CHILD it wires stdio to the PTY and returns pid 0.
    pid, master_fd = pty.fork()
    if pid == 0:
        # ---- child process ----
        try:
            os.chdir(workspace_path)
            os.execvpe(shell, [shell], env)  # replaces the child with the shell
        except Exception:  # noqa: BLE001 — child must never fall through to app code
            os._exit(127)

    # ---- parent process ----
    # Non-blocking so our reader never stalls the event loop when there's no output.
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    terminal = PtyTerminal(terminal_id, pid, master_fd, workspace_path)
    _terminals[terminal_id] = terminal
    logger.info("spawned terminal %s (%s) in %s", terminal_id, shell, workspace_path)
    return terminal_id


def _handle_control(terminal: PtyTerminal, text: str) -> None:
    """Handle a JSON control message from the client (currently just resize)."""
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return
    if message.get("type") == "resize":
        terminal.resize(int(message.get("rows", 24)), int(message.get("cols", 80)))


async def connect_pty(websocket: WebSocket, terminal_id: str) -> None:
    """Serve one /pty connection: pump PTY output → socket and socket input → PTY.

    Exists as the terminal's transport. Output is read off the master fd via the event
    loop's reader and queued so frames stay ordered; input arrives as binary frames
    (keystrokes) or text frames (resize control). On disconnect we always reap the shell.
    """
    terminal = _terminals.get(terminal_id)
    if terminal is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue()

    def on_readable() -> None:
        # Called by the event loop when the shell has output (or has exited).
        try:
            data = os.read(terminal.master_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return  # spurious wakeup; nothing to read yet
        except OSError:
            data = b""  # fd closed / shell gone → treat as EOF
        output.put_nowait(data if data else None)

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
                terminal.write(data)  # keystrokes
            elif (text := message.get("text")) is not None:
                _handle_control(terminal, text)  # resize
    except WebSocketDisconnect:
        pass
    finally:
        loop.remove_reader(terminal.master_fd)
        output.put_nowait(None)  # unblock the sender
        sender.cancel()
        _terminals.pop(terminal_id, None)
        # Reap off the event loop (it does short blocking waits).
        await asyncio.to_thread(terminal.close)
