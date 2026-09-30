# ─────────────────────────────────────────────────────────────────────────────
# test_workspaces.py — prove a Spec becomes a real, git-tracked directory.
# READING ORDER: backend #36
#
# We create a workspace from a Spec artifact in a temp location and assert the folder,
# the four scaffold files, and git all exist — plus that a name collision gets a "-2".
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import SQLModel, create_engine

from app import db
from app.models import Artifact, IdeationSession
from app.workspaces import manager

_SPEC_JSON = """{
  "project_name": "HabitDeck", "slug": "habit-deck",
  "one_liner": "A tiny daily checklist.", "problem": "Progress is invisible.",
  "target_user": "Someone building a routine.",
  "core_features": [
    {"name": "A", "description": "d", "acceptance": "a"},
    {"name": "B", "description": "d", "acceptance": "a"},
    {"name": "C", "description": "d", "acceptance": "a"}
  ],
  "non_goals": [], "tech_stack": {"backend": "FastAPI"}, "risks": [],
  "milestones": [
    {"name": "M1", "delivers": "x"}, {"name": "M2", "delivers": "y"},
    {"name": "M3", "delivers": "z"}
  ],
  "open_questions": []
}"""


def _setup(tmp_path: Path, monkeypatch) -> int:
    """Point db + workspaces dir at temp locations, insert a spec artifact, return its id."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    workspaces_dir = tmp_path / "workspaces"
    vault_dir = tmp_path / "state-vault"
    vault_dir.mkdir()
    monkeypatch.setattr(
        manager,
        "get_settings",
        lambda: SimpleNamespace(
            workspaces_dir=str(workspaces_dir),
            git_vault_dir=str(vault_dir),
        ),
    )

    with db.get_session() as session:
        session.add(
            IdeationSession(
                id="s1",
                title="HabitDeck",
                seed_prompt="a habit tracker",
                status="approved",
            )
        )
        artifact = Artifact(session_id="s1", kind="spec", version=1, content_json=_SPEC_JSON)
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        assert artifact.id is not None
        return artifact.id


def _create_or_skip(artifact_id: int):
    """Create a workspace, skipping only Apple's machine-level license gate."""
    try:
        return manager.create_from_spec(artifact_id)
    except RuntimeError as error:
        if "Xcode Command Line Tools license" in str(error):
            pytest.skip(str(error))
        raise


def test_create_from_spec_writes_files_and_git(tmp_path, monkeypatch) -> None:
    """A workspace has the four scaffold files, a git repo, and a persisted row."""
    artifact_id = _setup(tmp_path, monkeypatch)

    workspace = _create_or_skip(artifact_id)

    directory = Path(workspace.path)
    assert directory.is_dir()
    for name in ("SPEC.md", "spec.json", "CLAUDE.md", "aicompany.json"):
        assert (directory / name).is_file(), f"missing {name}"
    assert (directory / ".git").is_dir()
    # SPEC.md was rendered from the Spec (title present).
    assert "# HabitDeck" in (directory / "SPEC.md").read_text()
    # The row is persisted and findable.
    assert manager.get_workspace(workspace.id) is not None


def test_slug_collision_gets_suffix(tmp_path, monkeypatch) -> None:
    """Building the same Spec twice yields habit-deck and habit-deck-2."""
    artifact_id = _setup(tmp_path, monkeypatch)

    first = _create_or_skip(artifact_id)
    second = _create_or_skip(artifact_id)

    assert Path(first.path).name == "habit-deck"
    assert Path(second.path).name == "habit-deck-2"


def test_state_vault_is_a_validated_builtin_workspace(tmp_path, monkeypatch) -> None:
    """Automatic app-state history is visible without allowing arbitrary paths."""
    _setup(tmp_path, monkeypatch)

    workspaces = manager.list_workspaces()
    vault = next(item for item in workspaces if item.id == manager.STATE_VAULT_WORKSPACE_ID)

    assert vault.slug == "lemma-state-vault"
    assert manager.get_workspace(vault.id) is not None
    assert manager.validated_workspace_path(vault) == str((tmp_path / "state-vault").resolve())
