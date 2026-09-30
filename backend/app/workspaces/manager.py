# ─────────────────────────────────────────────────────────────────────────────
# manager.py — turn an approved Spec into a real, git-tracked project directory.
# READING ORDER: backend #33
#
# WHAT THIS FILE DOES:
#   create_from_spec() makes a folder under WORKSPACES_DIR, runs `git init`, writes the
#   files the coding agent needs (SPEC.md, spec.json, CLAUDE.md, aicompany.json), makes
#   the first commit, and records a Workspace row. It also opens the folder in the
#   user's editor or file manager.
#
# WHY a real directory with git: Phase 1 hands this folder to a coding agent (Claude
#   Code / Codex) that the user drives in the terminal. Git gives us the diff to review
#   later (M6). The directory lives OUTSIDE this repo (in ~/ai-company-workspaces) so
#   the agent's work never touches the app itself.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlmodel import select

from app.db import get_session
from app.ideation import repo
from app.ideation.schema import Spec
from app.ideation.spec_render import render_spec_markdown
from app.models import Workspace
from app.settings import BACKEND_DIR, get_settings
from app.shell_env import sanitized_env
from app.workspaces.gitutil import GIT_EXECUTABLE

logger = logging.getLogger("aicompany.workspaces")

# The application repository is always available as a built-in IDE workspace.  It is
# calculated from this installed source tree, never accepted from a request, so a
# client cannot turn the explorer into an arbitrary-path file browser.
PROJECT_WORKSPACE_ID = "lemma_project"
PROJECT_ROOT = BACKEND_DIR.parent.resolve(strict=True)
STATE_VAULT_WORKSPACE_ID = "lemma_vault"

# The briefing we drop into every workspace for the coding agent to read (PROMPT.md §10).
CLAUDE_MD = """# Mission
You are the coding agent building this project for a founder who is learning to program.
Read SPEC.md fully. Build milestone by milestone, committing after each.

# Rules
- Follow the Spec. If something is ambiguous or a bad idea, say so before coding around it.
- Explain significant decisions in commit messages — the founder reads git history to learn.
- Prefer boring, mainstream, well-documented technology.
- Never touch files outside this workspace.
"""


def _unique_dir(base: Path, slug: str) -> Path:
    """Return base/slug, adding -2, -3… if that name is already taken."""
    candidate = base / slug
    suffix = 2
    while candidate.exists():
        candidate = base / f"{slug}-{suffix}"
        suffix += 1
    return candidate


def _git(args: list[str], cwd: Path) -> None:
    """Run a git command in `cwd`, raising if it fails (so we notice a broken scaffold)."""
    env = sanitized_env(str(cwd))
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        subprocess.run(
            [
                GIT_EXECUTABLE,
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(cwd),
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
    except subprocess.CalledProcessError as error:
        stderr = error.stderr or ""
        if "Xcode license" in stderr:
            raise RuntimeError(
                "Git is unavailable until the Xcode Command Line Tools license is "
                "accepted in a local Terminal with `sudo xcodebuild -license`."
            ) from error
        raise RuntimeError("Git could not initialize the workspace") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Git is unavailable or did not respond") from error


def create_from_spec(spec_artifact_id: int) -> Workspace:
    """Create a workspace directory from a Spec artifact and record it. Returns the row.

    Exists as the one entry point for "make a project from this Spec". Synchronous
    (filesystem + git + subprocess), so async callers run it via asyncio.to_thread.
    """
    artifact = repo.get_artifact_by_id(spec_artifact_id)
    if artifact is None or artifact.kind != "spec":
        raise ValueError(f"artifact {spec_artifact_id} is not a spec")
    session = repo.get_session_row(artifact.session_id)
    if session is None or session.status != "approved":
        raise ValueError("a workspace can only be created from an approved session spec")

    spec = Spec.model_validate_json(artifact.content_json)

    base = Path(os.path.expanduser(get_settings().workspaces_dir))
    base.mkdir(parents=True, exist_ok=True)
    directory = _unique_dir(base, spec.slug)
    directory.mkdir()

    # Write the files the coding agent reads. SPEC.md uses the shared renderer so it
    # matches the export exactly; spec.json is the machine-readable source of truth.
    (directory / "SPEC.md").write_text(render_spec_markdown(spec), encoding="utf-8")
    (directory / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    (directory / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    # Seed checks empty; SPEC.md/UI tell the founder to fill it with commands that prove
    # the project works (tests, lint, build) — used by the Checks tab in M6.
    seed_checks = json.dumps({"checks": []}, indent=2)
    (directory / "aicompany.json").write_text(seed_checks, encoding="utf-8")

    # git init + a first commit, using a neutral identity so it works regardless of the
    # user's global git config.
    _git(["init", "-q"], directory)
    _git(["add", "-A"], directory)
    _git(
        [
            "-c",
            "user.name=Lemma",
            "-c",
            "user.email=noreply@ai-company.local",
            "commit",
            "-q",
            "-m",
            "chore: workspace scaffold from Spec",
        ],
        directory,
    )

    workspace = Workspace(
        id=f"ws_{uuid4().hex}",
        slug=directory.name,
        path=str(directory),
        spec_artifact_id=spec_artifact_id,
    )
    with get_session() as db:
        db.add(workspace)
        db.commit()
        db.refresh(workspace)

    logger.info("created workspace %s at %s", workspace.id, workspace.path)
    return workspace


def list_workspaces() -> list[Workspace]:
    """Return all workspaces, newest first — for the sidebar."""
    with get_session() as db:
        saved = list(db.exec(select(Workspace).order_by(Workspace.created_at.desc())))
    built_in_ids = {PROJECT_WORKSPACE_ID, STATE_VAULT_WORKSPACE_ID}
    return [
        _project_workspace(),
        _state_vault_workspace(),
        *[item for item in saved if item.id not in built_in_ids],
    ]


def get_workspace(workspace_id: str) -> Workspace | None:
    """Return one workspace by id, or None."""
    if workspace_id == PROJECT_WORKSPACE_ID:
        return _project_workspace()
    if workspace_id == STATE_VAULT_WORKSPACE_ID:
        return _state_vault_workspace()
    with get_session() as db:
        return db.get(Workspace, workspace_id)


def _project_workspace() -> Workspace:
    """Return the immutable virtual row for this checked-out Lemma repository."""
    return Workspace(
        id=PROJECT_WORKSPACE_ID,
        slug=PROJECT_ROOT.name,
        path=str(PROJECT_ROOT),
        spec_artifact_id=0,
        status="active",
    )


def _state_vault_workspace() -> Workspace:
    """Expose Lemma's automatic snapshots as a normal Source Control workspace."""
    root = Path(os.path.expanduser(get_settings().git_vault_dir)).resolve()
    return Workspace(
        id=STATE_VAULT_WORKSPACE_ID,
        slug="lemma-state-vault",
        path=str(root),
        spec_artifact_id=0,
        status="active",
    )


def validated_workspace_path(workspace: Workspace) -> str:
    """Return a canonical workspace path only when it remains inside the configured root."""
    candidate = Path(workspace.path).resolve(strict=True)
    if workspace.id == PROJECT_WORKSPACE_ID:
        if candidate != PROJECT_ROOT or not candidate.is_dir():
            raise ValueError("built-in project workspace path is invalid")
        return str(candidate)
    if workspace.id == STATE_VAULT_WORKSPACE_ID:
        configured = Path(os.path.expanduser(get_settings().git_vault_dir)).resolve(strict=True)
        if candidate != configured or not candidate.is_dir():
            raise ValueError("state vault workspace path is invalid")
        return str(candidate)

    base = Path(os.path.expanduser(get_settings().workspaces_dir)).resolve(strict=True)
    if not candidate.is_dir() or not candidate.is_relative_to(base):
        raise ValueError("workspace path is outside the configured workspace directory")
    return str(candidate)


def set_workspace_status(workspace_id: str, status: str) -> Workspace | None:
    """Flip a workspace's status (active ⇄ archived). The directory is NEVER deleted.

    Exists so archiving just hides a workspace from the main list (moving it to History);
    the files stay on disk so a restore reopens exactly where you left off.
    """
    with get_session() as db:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            return None
        workspace.status = status
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace


def open_in_editor(path: str) -> str:
    """Open `path` in the user's editor (or fall back to Reveal). Returns what happened.

    Tries $VISUAL, then $EDITOR, then `code` on PATH. If none exist, reveals the folder
    in the file manager instead, so the button always does *something* useful.
    """
    for candidate in (os.environ.get("VISUAL"), os.environ.get("EDITOR"), "code"):
        if candidate and shutil.which(candidate.split()[0]):
            # start_new_session detaches the editor so it keeps running after we return.
            subprocess.Popen([*candidate.split(), path], start_new_session=True)
            return f"opened in {candidate}"
    return reveal(path)


def reveal(path: str) -> str:
    """Reveal `path` in the OS file manager (`open` on macOS, `xdg-open` on Linux)."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(opener):
        subprocess.Popen([opener, path], start_new_session=True)
        return f"revealed with {opener}"
    return f"could not open a viewer; the path is {path}"
