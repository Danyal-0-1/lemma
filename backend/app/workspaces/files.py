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
_SKIP_DIRS = {
    ".git",
    ".ssh",
    ".aws",
    ".config",
    ".gnupg",
    ".kube",
    ".azure",
    "node_modules",
    ".venv",
    "__pycache__",
    "dist",
    ".vite",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".cache",
    "htmlcov",
}
_SENSITIVE_NAMES = {
    ".env",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
    ".coverage",
    ".ds_store",
}
_SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
}
_SENSITIVE_PREFIXES = {"backend/data"}
MAX_FILES = 10_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TREE_DEPTH = 40


def _is_sensitive(rel: str) -> bool:
    """Keep likely credential files out of the UI and mentor context."""
    candidate = Path(rel)
    normalized = candidate.as_posix().lower()
    name = candidate.name.lower()
    if (
        any(
            part.lower() in _SKIP_DIRS or part.lower().endswith(".egg-info")
            for part in candidate.parts
        )
        or any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in _SENSITIVE_PREFIXES
        )
    ):
        return True
    if name == ".env.example":
        return False
    return (
        name in _SENSITIVE_NAMES
        or name.startswith(".env.")
        or candidate.suffix.lower() in _SENSITIVE_SUFFIXES
    )


def is_available_path(rel: str) -> bool:
    """Return whether a relative path is safe to expose through the local IDE API."""
    candidate = Path(rel)
    return bool(
        rel
        and "\x00" not in rel
        and not candidate.is_absolute()
        and not any(part in {"", ".", ".."} for part in candidate.parts)
        and not _is_sensitive(rel)
    )


def list_files(path: str) -> dict:
    """Return {"files": [relative paths]} for the workspace, sorted, skipping noise dirs."""
    root = Path(path).resolve(strict=True)
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        directory = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not (directory / name).is_symlink()
            and is_available_path((directory / name).relative_to(root).as_posix())
        ]
        for filename in filenames:
            candidate = directory / filename
            rel = candidate.relative_to(root).as_posix()
            if not candidate.is_symlink() and is_available_path(rel):
                results.append(rel)
            if len(results) >= MAX_FILES:
                return {"files": sorted(results), "truncated": True}
    return {"files": sorted(results)}


def build_tree(path: str) -> dict:
    """Return a bounded hierarchical explorer tree without following symlinks."""
    root = Path(path).resolve(strict=True)
    count = 0
    truncated = False

    def visit(directory: Path, depth: int) -> list[dict]:
        nonlocal count, truncated
        if depth >= MAX_TREE_DEPTH:
            truncated = True
            return []
        try:
            candidates = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.casefold(), item.name),
            )
        except OSError:
            return []

        children: list[dict] = []
        for candidate in candidates:
            if count >= MAX_FILES:
                truncated = True
                break
            rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink() or _is_sensitive(rel):
                continue
            if candidate.is_dir():
                count += 1
                children.append(
                    {
                        "name": candidate.name,
                        "path": rel,
                        "type": "directory",
                        "children": visit(candidate, depth + 1),
                    }
                )
            elif candidate.is_file():
                count += 1
                children.append({"name": candidate.name, "path": rel, "type": "file"})
        return children

    tree = {
        "name": root.name,
        "path": "",
        "type": "directory",
        "children": visit(root, 0),
    }
    return {"root": tree, "truncated": truncated}


def read_file(path: str, rel: str, ref: str = "working") -> dict:
    """Return {"path", "content"} for one file — working tree, or HEAD when ref="head".

    Raises ValueError if `rel` resolves outside the workspace (path-traversal guard).
    """
    relative = Path(rel)
    if (
        not rel
        or "\x00" in rel
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not is_available_path(rel)
        or ref not in {"working", "head"}
    ):
        raise ValueError("file path is not available")

    root = Path(path).resolve(strict=True)
    unresolved = root / relative
    target = unresolved.resolve()
    if not target.is_relative_to(root):
        raise ValueError("path escapes the workspace")
    if unresolved.is_symlink():
        raise ValueError("symbolic links are not available")

    if ref == "head":
        # The committed version. Empty string if the file isn't in HEAD (e.g. it's new).
        content = git_output(["show", f"HEAD:{rel}"], root)
    elif target.is_file():
        try:
            if target.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("file is too large to display")
            content = target.read_text(errors="replace")
        except OSError:
            content = ""
    else:
        content = ""  # deleted or missing in the working tree

    if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        raise ValueError("file is too large to display")

    return {"path": rel, "content": content}
