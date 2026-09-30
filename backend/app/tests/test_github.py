"""Offline regressions for the GitHub account and remote boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.workspaces import github, gitutil, manager, source_control
from app.workspaces.gitutil import GitResult

TRUSTED_ORIGIN = "http://127.0.0.1:5173"


def test_github_status_uses_token_free_json_and_redacts_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "hosts": {
            "github.com": [
                {
                    "active": True,
                    "login": "researcher",
                    "state": "success",
                    "gitProtocol": "https",
                    "tokenSource": "/home/person/.config/gh/hosts.yml",
                    "token": "must-not-leak",
                }
            ]
        }
    }
    calls: list[list[str]] = []

    def run(args: list[str], _cwd: Path) -> GitResult:
        calls.append(args)
        return GitResult(0, json.dumps(document))

    monkeypatch.setattr(github, "GH_EXECUTABLE", "/usr/bin/gh")
    monkeypatch.setattr(github, "_run_gh", run)
    payload = github.github_connection_status(str(tmp_path))

    assert payload["authenticated"] is True
    assert payload["login"] == "researcher"
    assert payload["credential_storage"] == "github_cli_config"
    assert "must-not-leak" not in json.dumps(payload)
    assert "/home/person" not in json.dumps(payload)
    assert "--show-token" not in calls[0]
    assert calls[0][-2:] == ["--json", "hosts"]


def test_github_status_handles_missing_cli_without_running_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "GH_EXECUTABLE", None)
    payload = github.github_connection_status()
    assert payload["cli_installed"] is False
    assert payload["authenticated"] is False
    assert "gh auth login" in str(payload["message"])


@pytest.mark.parametrize(
    ("url", "protocol", "normalized"),
    [
        (
            "git@github.com:openai/lemma.git",
            "ssh",
            "git@github.com:openai/lemma.git",
        ),
        (
            "https://github.com/openai/lemma",
            "https",
            "https://github.com/openai/lemma.git",
        ),
        (
            "ssh://git@github.com/openai/lemma.git",
            "ssh",
            "ssh://git@github.com/openai/lemma.git",
        ),
    ],
)
def test_github_remote_validation_accepts_only_safe_repository_urls(
    url: str,
    protocol: str,
    normalized: str,
) -> None:
    value, metadata = source_control._validated_github_remote_url(url)
    assert value == normalized
    assert metadata["protocol"] == protocol
    assert metadata["owner"] == "openai"
    assert metadata["repository"] == "lemma"


@pytest.mark.parametrize(
    "url",
    [
        "https://token@github.com/openai/lemma.git",
        "https://github.com.evil.example/openai/lemma.git",
        "ssh://root@github.com/openai/lemma.git",
        "ssh://git@github.com:2222/openai/lemma.git",
        "file:///tmp/lemma.git",
        "https://github.com/openai/lemma/extra",
        "https://github.com/openai/%2e%2e",
    ],
)
def test_github_remote_validation_rejects_credentials_lookalikes_and_unsafe_urls(
    url: str,
) -> None:
    with pytest.raises(source_control.SourceControlError):
        source_control._validated_github_remote_url(url)


def test_configure_remote_and_upstream_are_local_git_only(tmp_path: Path) -> None:
    gitutil.git_run(["init", "-q"], tmp_path)
    gitutil.git_run(["branch", "-m", "main"], tmp_path)

    payload = source_control.configure_github_remote(
        str(tmp_path),
        "origin",
        "git@github.com:openai/lemma.git",
        set_upstream=True,
    )
    assert payload["upstream"] == "origin/main"
    assert payload["remotes"][0]["push"]["display"] == "github.com/openai/lemma"
    assert payload["remotes"][0]["credential_mode"] == "ssh"
    assert (
        gitutil.git_output(["config", "--local", "--get", "remote.origin.url"], tmp_path)
        == "git@github.com:openai/lemma.git\n"
    )

    updated = source_control.configure_github_remote(
        str(tmp_path),
        "origin",
        "https://github.com/openai/lemma-two",
    )
    assert updated["remotes"][0]["push"]["repository"] == "lemma-two"


def test_remote_info_never_returns_embedded_credentials(tmp_path: Path) -> None:
    gitutil.git_run(["init", "-q"], tmp_path)
    gitutil.git_run(
        ["remote", "add", "unsafe", "https://person:secret@github.com/owner/repo.git"],
        tmp_path,
    )
    payload = source_control.git_remote_info(str(tmp_path))
    encoded = json.dumps(payload)
    assert "person" not in encoded
    assert "secret" not in encoded
    assert payload["remotes"][0]["push"]["credentials_embedded"] is True
    assert payload["remotes"][0]["push_ready"] is False


def test_https_push_injects_only_the_github_cli_credential_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = {
        "repository": True,
        "branch": "main",
        "detached": False,
        "upstream": "origin/main",
        "ahead": 1,
        "behind": 0,
        "clean": True,
        "changes": [],
    }
    captured: list[list[str]] = []
    monkeypatch.setattr(source_control, "git_status", lambda _path: status)
    monkeypatch.setattr(
        source_control,
        "_configured_remote_url",
        lambda _root, _remote: "https://github.com/owner/repo.git",
    )
    monkeypatch.setattr(source_control, "_capture", lambda *_args, **_kwargs: GitResult(0, ""))
    monkeypatch.setattr(github, "GH_EXECUTABLE", "/usr/bin/gh")

    def capture(args: list[str], *_args, **_kwargs) -> GitResult:
        captured.append(args)
        return GitResult(0, "pushed")

    monkeypatch.setattr(source_control, "git_capture", capture)
    source_control.push_branch(str(tmp_path), "origin", "main", confirmed=True)

    command = captured[0]
    assert "credential.helper=" in command
    assert any("auth git-credential" in item for item in command)
    assert not any("token" in item.lower() for item in command)


def test_github_routes_report_status_and_gate_remote_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github,
        "github_connection_status",
        lambda: {
            "cli_installed": True,
            "authenticated": True,
            "login": "researcher",
        },
    )
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(enable_host_execution=False),
    )
    client = TestClient(app)
    try:
        status = client.get("/api/github/status")
        blocked = client.put(
            f"/api/workspaces/{manager.PROJECT_WORKSPACE_ID}/git/remotes/origin",
            json={"url": "git@github.com:openai/lemma.git"},
            headers={"Origin": TRUSTED_ORIGIN},
        )
    finally:
        client.close()

    assert status.status_code == 200
    assert status.json()["login"] == "researcher"
    assert blocked.status_code == 403
    assert "host execution is disabled" in blocked.json()["detail"]
