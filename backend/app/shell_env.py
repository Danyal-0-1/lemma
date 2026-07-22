# ─────────────────────────────────────────────────────────────────────────────
# shell_env.py — the ONE place we build the environment for any shell/subprocess.
# READING ORDER: backend #38
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  THE MOST EXPENSIVE BUG IN THIS APP LIVES OR DIES HERE.                   ║
# ║  Every shell we spawn — the interactive terminal AND the Checks runner —     ║
# ║  gets its environment from sanitized_env(). We DELETE ANTHROPIC_API_KEY and  ║
# ║  OPENAI_API_KEY so a `claude`/`codex` invocation uses the user's             ║
# ║  SUBSCRIPTION, not per-token API billing. Do not weaken this. It is defended ║
# ║  by test_pty.py.                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# WHY one shared function: the terminal and the checks runner must behave identically.
# Having a single sanitized_env() means the safety guarantee can't drift between them.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os


def sanitized_env(cwd: str) -> dict[str, str]:
    """Return a copy of the environment SAFE to hand to a spawned shell/subprocess.

    Strips the provider API keys (billing safety — see the banner above) and sets a
    sensible terminal type and working directory. Used by both the PTY terminal and the
    Checks runner so they can never diverge on this.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.setdefault("TERM", "xterm-256color")
    env["PWD"] = cwd
    return env
