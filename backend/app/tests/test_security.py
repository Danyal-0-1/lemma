"""Regression tests for Lemma's local-only and prompt-only security boundaries."""

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main as main_module
from app.main import app
from app.security import is_allowed_origin, is_safe_host
from app.settings import Settings
from app.shell_env import sanitized_env
from app.workspaces import checks, gitutil
from app.workspaces.files import read_file

TRUSTED_ORIGIN = "http://127.0.0.1:5173"


def test_host_and_origin_matching_is_exact() -> None:
    """Lookalike hosts and prefix/suffix origins must never pass local trust checks."""
    assert is_safe_host("127.0.0.1:8000")
    assert is_safe_host("[::1]:8000")
    assert not is_safe_host("127.0.0.1.evil.example:8000")
    assert not is_safe_host("localhost.evil.example")
    assert is_allowed_origin(TRUSTED_ORIGIN, [TRUSTED_ORIGIN])
    assert not is_allowed_origin(f"{TRUSTED_ORIGIN}/", [TRUSTED_ORIGIN])
    assert not is_allowed_origin(f"{TRUSTED_ORIGIN}.evil.example", [TRUSTED_ORIGIN])


def test_frontend_origins_must_remain_loopback() -> None:
    """Configuration cannot turn an exact-origin allowlist into a remote trust path."""
    safe = Settings(_env_file=None, frontend_origins="http://localhost:5173")
    assert safe.allowed_frontend_origins() == ["http://localhost:5173"]

    for unsafe in [
        "https://example.com:5173",
        "http://localhost:5173/path",
        "http://localhost",
        "http://user@localhost:5173",
    ]:
        configured = Settings(_env_file=None, frontend_origins=unsafe)
        with pytest.raises(RuntimeError, match="loopback origins"):
            configured.allowed_frontend_origins()


def test_mutations_require_origin_and_host_tools_remain_locked(monkeypatch) -> None:
    """A foreign webpage cannot mutate the API; trusted UI still hits the host lock."""
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(enable_host_execution=False),
    )
    client = TestClient(app)
    try:
        no_origin = client.post("/api/terminals", json={"workspace_id": "missing"})
        hostile = client.post(
            "/api/terminals",
            json={"workspace_id": "missing"},
            headers={"Origin": "https://evil.example"},
        )
        trusted = client.post(
            "/api/terminals",
            json={"workspace_id": "missing"},
            headers={"Origin": TRUSTED_ORIGIN},
        )
    finally:
        client.close()

    assert no_origin.status_code == 403
    assert no_origin.json()["detail"] == "untrusted request origin"
    assert hostile.status_code == 403
    assert trusted.status_code == 403
    assert "host execution is disabled" in trusted.json()["detail"]


def test_http_headers_and_websocket_origin() -> None:
    """HTTP responses are non-cacheable/non-frameable and sockets reject foreign origins."""
    client = TestClient(app)
    try:
        response = client.get("/health")
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/ws", headers={"Origin": "https://evil.example"}
            ):
                pass
    finally:
        client.close()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert rejected.value.code == 1008


def test_child_environment_is_an_allowlist(tmp_path, monkeypatch) -> None:
    """Present and future credentials stay out of terminal/check child processes."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    child = sanitized_env(str(tmp_path))

    assert child["PWD"] == str(tmp_path)
    assert child["LEMMA_WORKSPACE"] == str(tmp_path)
    assert not any("secret" in value for value in child.values())
    assert "GITHUB_TOKEN" not in child


def test_git_helpers_strip_secrets_config_and_bound_output(tmp_path, monkeypatch) -> None:
    """Even read-only Git helpers cannot inherit keys or buffer unlimited output."""
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    env = gitutil._environment(tmp_path)
    assert "OPENAI_API_KEY" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_TERMINAL_PROMPT"] == "0"

    monkeypatch.setattr(gitutil, "MAX_GIT_OUTPUT_BYTES", 128)
    monkeypatch.setattr(
        gitutil,
        "_command",
        lambda _args, _cwd: [sys.executable, "-c", "import sys; sys.stdout.write('x' * 4096)"],
    )
    assert gitutil.git_output([], tmp_path) == "x" * 128


def test_file_reads_reject_secrets_symlinks_and_sibling_prefixes(tmp_path) -> None:
    """A crafted relative path cannot escape a workspace or expose credential files."""
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "workspace-private"
    workspace.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("do-not-read", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (workspace / "outside-link").symlink_to(sibling / "secret.txt")

    with pytest.raises(ValueError):
        read_file(str(workspace), "../workspace-private/secret.txt")
    with pytest.raises(ValueError):
        read_file(str(workspace), ".env")
    with pytest.raises(ValueError):
        read_file(str(workspace), "outside-link")


def test_check_save_replaces_symlink_without_touching_target(tmp_path) -> None:
    """Saving checks cannot follow a malicious aicompany.json symlink."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("untouched", encoding="utf-8")
    (workspace / checks.CHECKS_FILENAME).symlink_to(outside)

    expected = [{"id": "tests", "name": "Tests", "command": "pytest"}]
    checks.write_checks(str(workspace), expected)

    assert outside.read_text(encoding="utf-8") == "untouched"
    assert checks.read_checks(str(workspace)) == expected
