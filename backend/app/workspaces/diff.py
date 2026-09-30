# ─────────────────────────────────────────────────────────────────────────────
# diff.py — what changed in a workspace since the last commit.
# READING ORDER: backend #40
#
# WHAT THIS FILE DOES: compares the working tree against the last commit (HEAD) and
# returns a per-file summary — path, lines added/deleted, and a status — plus the
# untracked (brand-new) files git wouldn't otherwise show in a diff.
#
# WHY vs HEAD: after the scaffold commit, everything the coding agent (or you) does is
# "since HEAD". That's exactly the review surface: what's new that you haven't committed.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from pathlib import Path

from app.workspaces.gitutil import git_output


def _count_lines(file_path: Path) -> int:
    """Return the line count of a text file (0 for binary/unreadable/non-files)."""
    if not file_path.is_file():
        return 0
    try:
        return len(file_path.read_text().splitlines())
    except (UnicodeDecodeError, OSError):
        return 0  # binary or unreadable — don't try to count "lines"


def compute_diff(path: str) -> dict:
    """Return {"files": [...]}: tracked changes vs HEAD plus untracked new files.

    Each entry is {path, additions, deletions, status}. Exists as the data behind the
    Diff tab's file list and the sidebar's +/- counts.
    """
    directory = Path(path)
    files: list[dict] = []

    # Tracked changes since the last commit. --numstat prints "adds<TAB>dels<TAB>path".
    numstat = git_output(
        ["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--numstat"], directory
    )
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, file_path = parts
        # Binary files show "-" instead of a number; treat those as 0.
        additions = int(added) if added.isdigit() else 0
        deletions = int(deleted) if deleted.isdigit() else 0
        status = "deleted" if not (directory / file_path).exists() else "modified"
        files.append(
            {"path": file_path, "additions": additions, "deletions": deletions, "status": status}
        )

    # Untracked (new) files — git diff won't show these, so we add them ourselves.
    porcelain = git_output(["status", "--porcelain"], directory)
    for line in porcelain.splitlines():
        if not line.startswith("??"):
            continue
        file_path = line[3:]
        additions = _count_lines(directory / file_path)
        files.append(
            {"path": file_path, "additions": additions, "deletions": 0, "status": "untracked"}
        )

    return {"files": files}
