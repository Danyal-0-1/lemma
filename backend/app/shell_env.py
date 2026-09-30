# ─────────────────────────────────────────────────────────────────────────────
# shell_env.py — the ONE place we build the environment for any shell/subprocess.
# READING ORDER: backend #38
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  THE MOST EXPENSIVE BUG IN THIS APP LIVES OR DIES HERE.                   ║
# ║  Every shell we spawn — the interactive terminal AND the Checks runner —     ║
# ║  gets its environment from sanitized_env(). We construct a small allowlist,   ║
# ║  so provider keys and every future credential stay private automatically.     ║
# ║  This also ensures a `claude`/`codex` invocation cannot silently inherit an    ║
# ║  API key and switch to metered billing. It is defended by security tests.      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# WHY one shared function: the terminal and the checks runner must behave identically.
# Having a single sanitized_env() means the safety guarantee can't drift between them.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os

# Construct, rather than subtract from, the child environment. New credentials added
# to the backend in the future therefore stay private automatically.
_SAFE_KEYS = {
    "PATH",
    "SHELL",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "COLORTERM",
    "TMPDIR",
}


def sanitized_env(cwd: str) -> dict[str, str]:
    """Return a copy of the environment SAFE to hand to a spawned shell/subprocess.

    Copies only ordinary shell/locale keys (billing and credential safety — see the
    banner above), then sets a terminal type and working directory. Used by both the
    PTY terminal and Checks runner so they cannot diverge on this boundary.
    """
    env = {key: value for key, value in os.environ.items() if key in _SAFE_KEYS}
    env.setdefault("TERM", "xterm-256color")
    env["PWD"] = cwd
    env["LEMMA_WORKSPACE"] = cwd
    return env
