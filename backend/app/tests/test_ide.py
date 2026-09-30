"""Security and parsing regressions for the VS Code-style local workbench."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.workspaces import gitutil, manager, source_control
from app.workspaces.files import build_tree
from app.workspaces.gitutil import GitResult

TRUSTED_ORIGIN = "http://127.0.0.1:5173"


def test_builtin_project_workspace_is_code_derived_and_immutable() -> None:
    workspace = manager.get_workspace(manager.PROJECT_WORKSPACE_ID)
    assert workspace is not None
    assert workspace.path == str(manager.PROJECT_ROOT)
    assert manager.validated_workspace_path(workspace) == str(manager.PROJECT_ROOT)

    forged = workspace.model_copy(update={"path": str(manager.PROJECT_ROOT.parent)})
    try:
        manager.validated_workspace_path(forged)
    except ValueError as error:
        assert "built-in project workspace" in str(error)
    else:  # pragma: no cover - explicit failure reads better than a helper here
        raise AssertionError("forged built-in workspace path was accepted")


def test_tree_hides_credentials_heavy_directories_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.js").write_text("", encoding="utf-8")
    outside = tmp_path.parent / "outside-ide-secret"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "linked-secret").symlink_to(outside)

    payload = build_tree(str(tmp_path))
    names = {child["name"] for child in payload["root"]["children"]}
    assert "src" in names
    assert ".env.example" in names
    assert ".env" not in names
    assert "node_modules" not in names
    assert "linked-secret" not in names


def test_porcelain_parser_handles_rename_dual_state_and_nul_names(tmp_path: Path) -> None:
    raw = "R  destination.py\x00source.py\x00MM both.py\x00?? new file.py\x00"
    changes = source_control._parse_porcelain(tmp_path.resolve(), raw)

    renamed = changes[0]
    assert renamed["path"] == "destination.py"
    assert renamed["original_path"] == "source.py"
    assert renamed["staged"] is True
    assert [change["staged"] for change in changes if change["path"] == "both.py"] == [True, False]
    assert changes[-1]["path"] == "new file.py"
    assert changes[-1]["status"] == "untracked"


def test_git_argv_disables_config_driven_execution(tmp_path: Path) -> None:
    command = gitutil._command(["status"], tmp_path)
    joined = "\n".join(command)
    assert "--literal-pathspecs" in command
    assert "core.hooksPath=/dev/null" in command
    assert "credential.helper=" in command
    assert "protocol.ext.allow=never" in command
    assert "protocol.file.allow=never" in command
    assert "commit.gpgSign=false" in command
    assert "ProxyCommand=none" in joined


def test_untracked_file_diff_uses_bounded_no_index_comparison(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "new file.py").write_text("print('new')\n", encoding="utf-8")
    calls: list[list[str]] = []

    def capture(_root: Path, args: list[str], **_kwargs) -> GitResult:
        calls.append(args)
        if "--no-index" in args:
            return GitResult(1, "diff --git a/new file.py b/new file.py\n+print('new')\n")
        return GitResult(0, "")

    monkeypatch.setattr(source_control, "_capture", capture)
    payload = source_control.git_diff(str(tmp_path), "new file.py")

    assert payload["patch"].startswith("diff --git")
    assert calls[-1][-2:] == ["/dev/null", "new file.py"]


def test_source_control_stage_unstage_and_commit_lifecycle(tmp_path: Path) -> None:
    """Exercise real Git writes only inside an isolated temporary repository."""
    gitutil.git_run(["init", "-q"], tmp_path)
    tracked = tmp_path / "notes.md"
    tracked.write_text("first\n", encoding="utf-8")
    gitutil.git_run(["add", "--", "notes.md"], tmp_path)
    gitutil.git_run(
        [
            "-c",
            "user.name=Lemma Test",
            "-c",
            "user.email=test@lemma.local",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
        tmp_path,
    )

    tracked.write_text("first\nsecond\n", encoding="utf-8")
    staged = source_control.stage_paths(str(tmp_path), ["notes.md"])
    assert any(change["path"] == "notes.md" and change["staged"] for change in staged["changes"])

    unstaged = source_control.unstage_paths(str(tmp_path), ["notes.md"])
    assert any(
        change["path"] == "notes.md" and not change["staged"]
        for change in unstaged["changes"]
    )

    source_control.stage_paths(str(tmp_path), ["notes.md"])
    committed = source_control.commit_changes(str(tmp_path), "docs: add a second line")
    assert committed["summary"] == "docs: add a second line"
    assert committed["status"]["clean"] is True


def test_push_requires_confirmation_before_inspecting_repository(tmp_path: Path) -> None:
    try:
        source_control.push_branch(
            str(tmp_path),
            "origin",
            "main",
            confirmed=False,
        )
    except source_control.SourceControlError as error:
        assert "confirmation" in str(error)
    else:  # pragma: no cover
        raise AssertionError("unconfirmed push was accepted")


def test_remote_validation_rejects_credentials_and_non_network_protocols(
    tmp_path: Path,
    monkeypatch,
) -> None:
    responses = iter(
        [
            GitResult(1, ""),
            GitResult(0, "https://user:secret@example.test/repo.git\n"),
        ]
    )
    monkeypatch.setattr(source_control, "_capture", lambda *_args, **_kwargs: next(responses))
    try:
        source_control._configured_remote_url(tmp_path, "origin")
    except source_control.SourceControlError as error:
        assert "credentials embedded" in str(error)
    else:  # pragma: no cover
        raise AssertionError("credential-bearing URL was accepted")

    responses = iter([GitResult(1, ""), GitResult(0, "file:///tmp/repo\n")])
    monkeypatch.setattr(source_control, "_capture", lambda *_args, **_kwargs: next(responses))
    try:
        source_control._configured_remote_url(tmp_path, "origin")
    except source_control.SourceControlError as error:
        assert "HTTPS and SSH" in str(error)
    else:  # pragma: no cover
        raise AssertionError("file remote was accepted")


def test_source_control_mutations_are_host_execution_gated(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(enable_host_execution=False),
    )
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/workspaces/{manager.PROJECT_WORKSPACE_ID}/git/stage",
            json={"paths": ["README.md"]},
            headers={"Origin": TRUSTED_ORIGIN},
        )
    finally:
        client.close()
    assert response.status_code == 403
    assert "host execution is disabled" in response.json()["detail"]
