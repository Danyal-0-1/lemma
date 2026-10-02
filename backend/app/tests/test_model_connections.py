"""Security and routing tests for explicit model connections."""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from app.providers.base import ChatMessage
from app.providers.connections import (
    ConnectionDescriptor,
    ModelConnectionError,
    connection_catalog,
    validate_connection_model,
)
from app.providers.factory import get_provider
from app.providers.litellm_provider import LiteLLMProvider
from app.providers.subscription_cli_provider import (
    CODEX_DISABLED_FEATURES,
    GEMINI_DENY_ALL_POLICY,
    SubscriptionCLIProvider,
)
from app.settings import Settings


def _subscription(
    connection_id: str, executable: str = "/trusted/vendor-cli"
) -> ConnectionDescriptor:
    return ConnectionDescriptor(
        id=connection_id,
        name=connection_id,
        provider="test",
        kind="subscription",
        auth_mode="account_session",
        egress="remote",
        billing="subscription",
        configured=True,
        status="available",
        models=("default",),
        supports_custom_model=True,
        detail="test",
        setup="test",
        executable=executable,
    )


async def test_litellm_forwards_explicit_key_and_base_per_call(monkeypatch) -> None:
    """Credentials loaded from .env are passed directly, not ambiently inferred."""
    captured: dict[str, Any] = {}
    sentinel = object()

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("app.providers.litellm_provider.litellm.acompletion", fake_completion)
    provider = LiteLLMProvider(
        api_key="provider-secret",
        api_base="https://models.example.test/v1",
    )

    result = await provider._open_stream(  # noqa: SLF001 - this is the request boundary
        "openai/research-model",
        [{"role": "user", "content": "hello"}],
        max_output_tokens=500,
    )

    assert result is sentinel
    assert captured["api_key"] == "provider-secret"
    assert captured["api_base"] == "https://models.example.test/v1"
    assert captured["max_tokens"] == 500
    assert captured["stream"] is True


def test_public_catalog_and_provenance_never_expose_secrets_or_targets(tmp_path) -> None:
    """Browser metadata and stored provenance reveal neither keys nor machine paths."""
    executable = tmp_path / "private" / "vendor-cli"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    settings = Settings(
        _env_file=None,
        mock_llm=False,
        openai_api_key="openai-super-secret",
        LEMMA_CUSTOM_OPENAI_API_KEY="custom-super-secret",
        LEMMA_CUSTOM_OPENAI_BASE_URL="https://private-model-host.example/v1",
        LEMMA_CUSTOM_OPENAI_MODELS="openai/private-model",
        LEMMA_CODEX_EXECUTABLE=str(executable),
        LEMMA_CLAUDE_EXECUTABLE=str(executable),
        LEMMA_GEMINI_EXECUTABLE=str(executable),
    )

    catalog = connection_catalog(settings)
    public = json.dumps([connection.public_dict() for connection in catalog])
    provenance = json.dumps([connection.provenance() for connection in catalog])

    for private_value in (
        "openai-super-secret",
        "custom-super-secret",
        "private-model-host.example",
        str(executable),
        str(executable.parent),
    ):
        assert private_value not in public
        assert private_value not in provenance
    assert all("api_key" not in connection.public_dict() for connection in catalog)
    assert all("base_url" not in connection.public_dict() for connection in catalog)
    assert all("executable" not in connection.public_dict() for connection in catalog)
    assert all(len(connection.provenance()["target_sha256"]) == 64 for connection in catalog)


def test_catalog_rejects_group_writable_subscription_executable(tmp_path) -> None:
    executable = tmp_path / "replaceable-cli"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o775)
    settings = Settings(_env_file=None, LEMMA_CLAUDE_EXECUTABLE=str(executable))

    catalog = {connection.id: connection for connection in connection_catalog(settings)}

    assert catalog["claude-subscription"].configured is False
    assert catalog["claude-subscription"].status == "setup_required"


def test_factory_routes_explicit_connections_without_network(tmp_path) -> None:
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    settings = Settings(
        _env_file=None,
        mock_llm=False,
        openai_api_key="openai-secret",
        LEMMA_OLLAMA_BASE_URL="http://127.0.0.1:11434",
        LEMMA_CLAUDE_EXECUTABLE=str(executable),
    )

    api_provider = get_provider(settings, "openai-api", "openai/research-model")
    legacy_api_provider = get_provider(settings, "legacy", "openai/research-model")
    local_provider = get_provider(settings, "ollama-local", "ollama/qwen3")
    subscription_provider = get_provider(settings, "claude-subscription", "sonnet")

    assert isinstance(api_provider, LiteLLMProvider)
    assert api_provider._api_key == "openai-secret"  # noqa: SLF001
    assert isinstance(legacy_api_provider, LiteLLMProvider)
    assert legacy_api_provider._api_key == "openai-secret"  # noqa: SLF001
    assert isinstance(local_provider, LiteLLMProvider)
    assert local_provider._api_base == "http://127.0.0.1:11434"  # noqa: SLF001
    assert isinstance(subscription_provider, SubscriptionCLIProvider)
    with pytest.raises(ModelConnectionError, match="must start with"):
        validate_connection_model("openai-api", "anthropic/claude", settings=settings)
    with pytest.raises(ModelConnectionError, match="unsupported characters"):
        validate_connection_model("openai-api", "openai/model;rm", settings=settings)
    unconfigured = Settings(_env_file=None, mock_llm=False, openai_api_key="")
    with pytest.raises(ModelConnectionError, match="not configured"):
        get_provider(unconfigured, "openai-api", "openai/research-model")


def test_subscription_commands_disable_customization_and_tools(tmp_path) -> None:
    directory = "/private/empty"
    output = f"{directory}/answer.txt"
    instructions = f"{directory}/model-instructions.md"
    codex = SubscriptionCLIProvider(_subscription("chatgpt-subscription"), timeout_seconds=30)
    claude = SubscriptionCLIProvider(_subscription("claude-subscription"), timeout_seconds=30)
    gemini = SubscriptionCLIProvider(_subscription("gemini-subscription"), timeout_seconds=30)

    codex_argv = codex._argv(  # noqa: SLF001
        "default", directory, output, instructions
    )
    claude_argv = claude._argv(  # noqa: SLF001
        "sonnet", directory, output, instructions
    )
    gemini_argv = gemini._argv(  # noqa: SLF001
        "auto", directory, output, instructions
    )

    expected_codex = ["/trusted/vendor-cli"]
    for feature in CODEX_DISABLED_FEATURES:
        expected_codex.extend(["--disable", feature])
    expected_codex.extend(
        [
            "-c",
            'web_search="disabled"',
            "-c",
            "mcp_servers={}",
            "-c",
            f'model_instructions_file="{instructions}"',
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--json",
            "--cd",
            directory,
            "--output-last-message",
            output,
            "-",
        ]
    )
    assert codex_argv == expected_codex
    assert "--restricted" in claude_argv
    assert "--safe-mode" in claude_argv
    assert claude_argv[claude_argv.index("--tools") + 1] == ""
    assert claude_argv[claude_argv.index("--permission-prompts") + 1] == "none"
    assert claude_argv[claude_argv.index("--append-system-prompt-file") + 1] == instructions
    assert gemini_argv == [
        "/trusted/vendor-cli",
        "--output-format",
        "json",
        "--approval-mode",
        "default",
        "--extensions",
        "none",
        "--policy",
        f"{directory}/deny-all-tools.toml",
        "--prompt",
        "",
    ]

    safety_directory = tmp_path / "gemini-safety"
    safety_directory.mkdir()
    env: dict[str, str] = {}
    gemini._prepare_gemini_safety_config(str(safety_directory), env)  # noqa: SLF001
    policy_path = safety_directory / "deny-all-tools.toml"
    settings_path = safety_directory / "system-settings.json"
    assert policy_path.read_text(encoding="utf-8") == GEMINI_DENY_ALL_POLICY
    assert stat.S_IMODE(policy_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(settings_path)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "context": {
            "fileName": [],
            "includeDirectories": [],
            "includeDirectoryTree": False,
            "memoryBoundaryMarkers": [],
        },
        "hooksConfig": {"enabled": False},
        "mcp": {"allowed": []},
        "security": {
            "disableAlwaysAllow": True,
            "disableYoloMode": True,
            "enablePermanentToolApproval": False,
        },
        "telemetry": {"enabled": False, "logPrompts": False},
        "tools": {"core": []},
    }
    instruction_path = gemini._prepare_instruction_file(  # noqa: SLF001
        str(safety_directory), "trusted system instruction", env
    )
    assert instruction_path is not None
    assert Path(instruction_path).read_text(encoding="utf-8") == "trusted system instruction"
    assert stat.S_IMODE(Path(instruction_path).stat().st_mode) == 0o600
    assert env["GEMINI_SYSTEM_MD"] == instruction_path


def test_subscription_separates_system_from_untrusted_conversation() -> None:
    provider = SubscriptionCLIProvider(
        _subscription("chatgpt-subscription"), timeout_seconds=30
    )

    system, user = provider._prompts(  # noqa: SLF001
        [
            ChatMessage(role="system", content="trusted rule"),
            ChatMessage(role="user", content="research input"),
            ChatMessage(role="assistant", content="earlier answer"),
        ]
    )

    assert system == "trusted rule"
    assert "trusted rule" not in user
    assert "USER MESSAGE:\nresearch input" in user
    assert "ASSISTANT MESSAGE:\nearlier answer" in user


class _FakeStdin:
    def __init__(self) -> None:
        self.content = b""
        self.closed = False

    def write(self, content: bytes) -> None:
        self.content += content

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, stdout: bytes) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self.pid = 999_999_999

    async def wait(self) -> int:
        self.returncode = 0
        return 0


class _HangingProcess(_FakeProcess):
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.pid = 999_999_998

    async def wait(self) -> int:
        await asyncio.Event().wait()
        return 0


async def test_subscription_invoke_uses_isolated_bounded_secret_free_process(
    monkeypatch,
) -> None:
    """The CLI receives the prompt on stdin in a temporary cwd with an allowlist env."""
    captured: dict[str, Any] = {}
    process = _FakeProcess(b'{"result":"connected","usage":{"input_tokens":4,"output_tokens":2}}')

    async def fake_subprocess(*argv, **kwargs):
        captured.update({"argv": argv, **kwargs})
        instruction_index = argv.index("--append-system-prompt-file") + 1
        instruction_path = Path(argv[instruction_index])
        captured["instruction_content"] = instruction_path.read_text(encoding="utf-8")
        captured["instruction_mode"] = stat.S_IMODE(instruction_path.stat().st_mode)
        return process

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = SubscriptionCLIProvider(_subscription("claude-subscription"), timeout_seconds=30)

    answer, raw = await provider._invoke(  # noqa: SLF001
        "sonnet", "private system prompt", "user prompt"
    )

    assert answer == "connected"
    assert b'"result":"connected"' in raw
    assert process.stdin.content == b"user prompt"
    assert process.stdin.closed is True
    assert captured["instruction_content"] == "private system prompt"
    assert captured["instruction_mode"] == 0o600
    assert all("private system prompt" not in argument for argument in captured["argv"])
    assert captured["start_new_session"] is True
    temporary_cwd = Path(captured["cwd"])
    assert temporary_cwd.name.startswith("lemma-model-")
    assert not temporary_cwd.exists()
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "ANTHROPIC_API_KEY" not in captured["env"]


async def test_subscription_bounds_input_output_and_rejects_result_symlinks(
    tmp_path, monkeypatch
) -> None:
    provider = SubscriptionCLIProvider(_subscription("claude-subscription"), timeout_seconds=30)
    monkeypatch.setattr(
        "app.providers.subscription_cli_provider.MAX_STDIN_BYTES",
        4,
    )
    with pytest.raises(RuntimeError, match="prompt exceeded"):
        await provider._invoke("sonnet", "", "12345")  # noqa: SLF001

    reader = asyncio.StreamReader()
    reader.feed_data(b"12345")
    reader.feed_eof()
    with pytest.raises(RuntimeError, match="output exceeded"):
        await provider._bounded_read(reader, 4)  # noqa: SLF001

    outside = tmp_path / "outside"
    outside.write_text("private", encoding="utf-8")
    link = tmp_path / "answer"
    link.symlink_to(outside)
    with pytest.raises(RuntimeError, match="unsafe"):
        provider._read_output_file(link)  # noqa: SLF001


async def test_subscription_timeout_stops_process_and_cancels_readers(monkeypatch) -> None:
    process = _HangingProcess()
    stopped: list[_HangingProcess] = []

    async def fake_subprocess(*_argv, **_kwargs):
        return process

    async def fake_stop(target) -> None:
        stopped.append(target)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    provider = SubscriptionCLIProvider(_subscription("claude-subscription"), timeout_seconds=0.01)
    monkeypatch.setattr(provider, "_stop", fake_stop)

    with pytest.raises(TimeoutError):
        await provider._invoke("sonnet", "system", "bounded prompt")  # noqa: SLF001

    assert stopped == [process]
