# ─────────────────────────────────────────────────────────────────────────────
# test_workspaces.py — prove a Spec becomes a real, git-tracked directory.
# READING ORDER: backend #36
#
# We create a workspace from a Spec artifact in a temp location and assert the folder,
# the four scaffold files, and git all exist — plus that a name collision gets a "-2".
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path
from types import SimpleNamespace

from sqlmodel import SQLModel, create_engine

from app import db
from app.models import Artifact
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
    monkeypatch.setattr(
        manager, "get_settings", lambda: SimpleNamespace(workspaces_dir=str(workspaces_dir))
    )

    with db.get_session() as session:
        artifact = Artifact(session_id="s1", kind="spec", version=1, content_json=_SPEC_JSON)
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        assert artifact.id is not None
        return artifact.id


def test_create_from_spec_writes_files_and_git(tmp_path, monkeypatch) -> None:
    """A workspace has the four scaffold files, a git repo, and a persisted row."""
    artifact_id = _setup(tmp_path, monkeypatch)

    workspace = manager.create_from_spec(artifact_id)

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

    first = manager.create_from_spec(artifact_id)
    second = manager.create_from_spec(artifact_id)

    assert Path(first.path).name == "habit-deck"
    assert Path(second.path).name == "habit-deck-2"
