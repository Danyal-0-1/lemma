# ─────────────────────────────────────────────────────────────────────────────
# files.py — read the files in a workspace (for the read-only Files tab).
# READING ORDER: backend #41
#
# WHAT THIS FILE DOES: lists the files in a workspace (skipping heavy/irrelevant dirs)
# and reads one file's content — either the working-tree version or the committed (HEAD)
# version (the latter is how the Diff tab gets the "before" side).
#
# WHY the path check in read_file: `rel` comes from the client. We resolve it and make
# sure it stays INSIDE the workspace, so a crafted "../../etc/passwd" can't escape.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
from pathlib import Path

from app.workspaces.gitutil import git_output

# Directories we never show — noise or huge, and never what you're reviewing.
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", ".vite", ".ruff_cache"}


def list_files(path: str) -> dict:
    """Return {"files": [relative paths]} for the workspace, sorted, skipping noise dirs."""
    root = Path(path)
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Pruning dirnames in place stops os.walk from descending into skipped dirs.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            results.append(os.path.relpath(os.path.join(dirpath, filename), root))
    return {"files": sorted(results)}


def read_file(path: str, rel: str, ref: str = "working") -> dict:
    """Return {"path", "content"} for one file — working tree, or HEAD when ref="head".

    Raises ValueError if `rel` resolves outside the workspace (path-traversal guard).
    """
    root = Path(path).resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("path escapes the workspace")

    if ref == "head":
        # The committed version. Empty string if the file isn't in HEAD (e.g. it's new).
        content = git_output(["show", f"HEAD:{rel}"], root)
    elif target.is_file():
        try:
            content = target.read_text(errors="replace")
        except OSError:
            content = ""
    else:
        content = ""  # deleted or missing in the working tree

    return {"path": rel, "content": content}
