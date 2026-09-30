# ─────────────────────────────────────────────────────────────────────────────
# test_diff.py — prove the diff sees both a modified file and a new (untracked) one.
# READING ORDER: backend #43
#
# We build a tiny git repo, commit a file, then change it and add a new file. The diff
# must report the modification (with line counts) AND the untracked file — the exact
# two cases the Diff tab needs to show.
# ─────────────────────────────────────────────────────────────────────────────

import subprocess
from pathlib import Path

import pytest

from app.workspaces.diff import compute_diff


def _run(args: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    )
    if result.returncode == 69 and "Xcode license" in result.stderr:
        pytest.skip("Apple Git is unavailable until the local Xcode license is accepted")
    result.check_returncode()


def _init_repo(path: Path) -> None:
    """Create a git repo with one committed file (a.txt)."""
    _run(["init", "-q"], path)
    (path / "a.txt").write_text("line1\nline2\n")
    _run(["add", "-A"], path)
    _run(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], path)


def test_diff_reports_modified_and_untracked(tmp_path) -> None:
    """A changed tracked file and a brand-new file both appear in the diff."""
    _init_repo(tmp_path)

    # Modify the tracked file and add an untracked one.
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n")
    (tmp_path / "b.txt").write_text("brand new\n")

    result = compute_diff(str(tmp_path))
    by_path = {entry["path"]: entry for entry in result["files"]}

    assert "a.txt" in by_path
    assert by_path["a.txt"]["status"] == "modified"
    assert by_path["a.txt"]["additions"] >= 1

    assert "b.txt" in by_path
    assert by_path["b.txt"]["status"] == "untracked"
    assert by_path["b.txt"]["additions"] == 1


def test_diff_clean_repo_is_empty(tmp_path) -> None:
    """With nothing changed since the commit, the diff is empty."""
    _init_repo(tmp_path)
    assert compute_diff(str(tmp_path))["files"] == []
