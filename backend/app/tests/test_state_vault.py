"""Regression tests for the credential-safe local Git state vault."""

import json
from pathlib import Path

from app import state_vault
from app.workspaces import source_control


def test_sanitize_redacts_credentials_but_not_usage_counts() -> None:
    value = state_vault._sanitize(
        {
            "api_key": "secret",
            "nested": {"access-token": "secret", "tokens_in": 42},
            "content": "ordinary research",
        }
    )
    assert value["api_key"] == "[redacted]"
    assert value["nested"]["access-token"] == "[redacted]"
    assert value["nested"]["tokens_in"] == 42
    assert value["content"] == "ordinary research"


def test_vault_creates_local_commits_without_a_remote(tmp_path: Path, monkeypatch) -> None:
    counter = {"value": 1}

    def snapshot() -> str:
        return json.dumps(
            {"format": state_vault.VAULT_FORMAT, "tables": {"revision": [counter["value"]]}},
            indent=2,
            sort_keys=True,
        ) + "\n"

    monkeypatch.setattr(state_vault, "render_snapshot", snapshot)
    assert state_vault.sync_vault(tmp_path) is True
    assert state_vault.sync_vault(tmp_path) is False

    counter["value"] = 2
    assert state_vault.sync_vault(tmp_path) is True
    status = source_control.git_status(str(tmp_path))
    assert status["repository"] is True
    assert status["clean"] is True
    assert status["upstream"] is None
    assert "secret" not in (tmp_path / state_vault.SNAPSHOT_FILE).read_text()
