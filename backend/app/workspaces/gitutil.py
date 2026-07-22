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

import subprocess
from pathlib import Path


def git_run(args: list[str], cwd: Path) -> None:
    """Run a git command that must succeed (raises CalledProcessError otherwise)."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def git_output(args: list[str], cwd: Path) -> str:
    """Run a read-only git query and return its stdout, ignoring a non-zero exit.

    Exists for `diff` / `status` / `show` where a non-zero exit is a normal outcome
    (e.g. `git show HEAD:new_file` fails because the file isn't in HEAD yet).
    """
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return result.stdout
