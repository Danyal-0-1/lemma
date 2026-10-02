"""Explicit, redacted model-connection catalog and routing metadata.

Connections are intentionally configured from the backend environment rather than
from browser storage.  API keys never enter SQLite, snapshots, logs, or responses.
An agent stores a stable connection id plus a model id so API billing, account-plan
usage, local inference, and custom endpoints cannot be confused or silently swapped.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import get_config
from app.settings import LOCAL_HOSTS, Settings, get_settings

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class ModelConnectionError(ValueError):
    """A selected connection or model is invalid or not configured."""


@dataclass(frozen=True)
class ConnectionDescriptor:
    id: str
    name: str
    provider: str
    kind: str
    auth_mode: str
    egress: str
    billing: str
    configured: bool
    status: str
    models: tuple[str, ...]
    supports_custom_model: bool
    detail: str
    setup: str
    api_key: str = ""
    base_url: str = ""
    executable: str = ""

    def public_dict(self) -> dict[str, Any]:
        """Return browser-safe metadata; credentials and private paths stay server-side."""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "kind": self.kind,
            "auth_mode": self.auth_mode,
            "status": self.status,
            "egress": self.egress,
            "billing": self.billing,
            "configured": self.configured,
            "models": [{"id": model, "label": model} for model in self.models],
            "supports_custom_model": self.supports_custom_model,
            "detail": self.detail,
            "setup": self.setup,
        }

    def provenance(self) -> dict[str, str]:
        """Freeze non-secret routing identity for runs and model-call audit records."""
        target = self.base_url or self.executable or f"provider:{self.provider}"
        return {
            "id": self.id,
            "provider": self.provider,
            "kind": self.kind,
            "auth_mode": self.auth_mode,
            "egress": self.egress,
            "billing": self.billing,
            "target_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        }


def _csv(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _configured_models(prefix: str) -> tuple[str, ...]:
    config = get_config()
    candidates = [*config.roles.values(), *config.pricing]
    return tuple(dict.fromkeys(model for model in candidates if model.startswith(prefix)))


def _safe_executable(configured: str, command: str) -> str:
    candidate = configured.strip()
    if candidate:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            return ""
    else:
        found = shutil.which(command)
        if not found:
            return ""
        path = Path(found)
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError:
        return ""
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return ""
    # A CLI is trusted with the user's authenticated account session. Refuse paths
    # another local account could replace without the owner noticing.
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        return ""
    return str(resolved)


def _base_url(value: str, *, loopback_only: bool) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/v1"}
    ):
        return ""
    is_loopback = hostname in LOCAL_HOSTS
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        is_loopback = address.is_loopback
        if not is_loopback and not address.is_global:
            return ""
    if loopback_only and not is_loopback:
        return ""
    if not is_loopback and parsed.scheme != "https":
        return ""
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def connection_catalog(settings: Settings | None = None) -> list[ConnectionDescriptor]:
    configured = settings or get_settings()
    codex = _safe_executable(configured.codex_executable, "codex")
    claude = _safe_executable(configured.claude_executable, "claude")
    gemini = _safe_executable(configured.gemini_executable, "gemini")
    ollama_url = _base_url(configured.ollama_base_url, loopback_only=True)
    custom_url = _base_url(configured.custom_openai_base_url, loopback_only=False)

    def api(
        connection_id: str,
        name: str,
        provider: str,
        key: str,
        prefix: str,
        env_name: str,
    ) -> ConnectionDescriptor:
        ready = bool(key.strip())
        return ConnectionDescriptor(
            id=connection_id,
            name=name,
            provider=provider,
            kind="api_key",
            auth_mode="api_key",
            egress="remote",
            billing="api",
            configured=ready,
            status="ready" if ready else "setup_required",
            models=_configured_models(prefix),
            supports_custom_model=True,
            detail="Direct provider API; usage is metered separately from consumer plans.",
            setup=f"Set {env_name} in backend/.env, set MOCK_LLM=false, then restart Lemma.",
            api_key=key.strip(),
        )

    def subscription(
        connection_id: str,
        name: str,
        provider: str,
        executable: str,
        command: str,
        models: tuple[str, ...],
    ) -> ConnectionDescriptor:
        available = bool(executable)
        return ConnectionDescriptor(
            id=connection_id,
            name=name,
            provider=provider,
            kind="subscription",
            auth_mode="account_session",
            egress="remote",
            billing="subscription",
            configured=available,
            status="available" if available else "setup_required",
            models=models,
            supports_custom_model=True,
            detail=(
                "Uses the official local CLI account session and its plan allowance; "
                "it never falls back to an API key."
            ),
            setup=(
                f"Install and run `{command}` once in your system terminal to sign in, then set "
                f"LEMMA_{command.upper()}_EXECUTABLE to its absolute path if it is not on PATH."
            ),
            executable=executable,
        )

    custom_ready = bool(custom_url)
    return [
        ConnectionDescriptor(
            id="mock",
            name="Mock / demo",
            provider="mock",
            kind="legacy",
            auth_mode="none",
            egress="local",
            billing="none",
            configured=True,
            status="ready",
            models=("mock/research",),
            supports_custom_model=False,
            detail="Deterministic local demo responses; no network and no cost.",
            setup="Set MOCK_LLM=true (the default).",
        ),
        api(
            "deepseek-api",
            "DeepSeek API",
            "deepseek",
            configured.deepseek_api_key,
            "deepseek/",
            "DEEPSEEK_API_KEY",
        ),
        api(
            "openai-api",
            "OpenAI API",
            "openai",
            configured.openai_api_key,
            "openai/",
            "OPENAI_API_KEY",
        ),
        api(
            "anthropic-api",
            "Anthropic API",
            "anthropic",
            configured.anthropic_api_key,
            "anthropic/",
            "ANTHROPIC_API_KEY",
        ),
        api(
            "gemini-api",
            "Gemini API",
            "gemini",
            configured.gemini_api_key,
            "gemini/",
            "GEMINI_API_KEY",
        ),
        subscription(
            "chatgpt-subscription",
            "ChatGPT plan via Codex CLI",
            "openai",
            codex,
            "codex",
            ("default",),
        ),
        subscription(
            "claude-subscription",
            "Claude plan via Claude Code",
            "anthropic",
            claude,
            "claude",
            ("sonnet", "opus"),
        ),
        subscription(
            "gemini-subscription",
            "Google AI plan via Gemini CLI",
            "gemini",
            gemini,
            "gemini",
            ("auto",),
        ),
        ConnectionDescriptor(
            id="ollama-local",
            name="Ollama on this computer",
            provider="ollama",
            kind="local",
            auth_mode="none",
            egress="local",
            billing="none",
            configured=bool(ollama_url),
            status="available" if ollama_url else "error",
            models=_csv(configured.ollama_models),
            supports_custom_model=True,
            detail="Loopback-only Ollama endpoint. Add exact IDs to the local-model attestation.",
            setup=(
                "Install/start Ollama, set LEMMA_OLLAMA_MODELS and LEMMA_LOCAL_MODEL_IDS "
                "in backend/.env, then restart Lemma."
            ),
            base_url=ollama_url,
        ),
        ConnectionDescriptor(
            id="custom-openai",
            name="Custom OpenAI-compatible endpoint",
            provider="custom",
            kind="custom",
            auth_mode="api_key" if configured.custom_openai_api_key else "none",
            egress=(
                "local"
                if custom_url and urlsplit(custom_url).hostname in LOCAL_HOSTS
                else "operator_defined"
            ),
            billing="custom",
            configured=custom_ready,
            status="ready" if custom_ready else "setup_required",
            models=_csv(configured.custom_openai_models),
            supports_custom_model=True,
            detail="OpenAI-compatible server; billing and data handling are set by its operator.",
            setup=(
                "Set LEMMA_CUSTOM_OPENAI_BASE_URL, optional LEMMA_CUSTOM_OPENAI_API_KEY, "
                "and LEMMA_CUSTOM_OPENAI_MODELS in backend/.env, then restart Lemma."
            ),
            api_key=configured.custom_openai_api_key.strip(),
            base_url=custom_url,
        ),
        ConnectionDescriptor(
            id="legacy",
            name="Legacy config.toml route",
            provider="legacy",
            kind="legacy",
            auth_mode="api_key",
            egress="remote",
            billing="api",
            configured=True,
            status="available",
            models=tuple(dict.fromkeys(get_config().roles.values())),
            supports_custom_model=False,
            detail="Compatibility route for agents created before explicit connections.",
            setup="Choose an explicit connection when you next edit this agent.",
        ),
    ]


def get_connection(
    connection_id: str,
    *,
    model: str = "",
    settings: Settings | None = None,
) -> ConnectionDescriptor:
    """Resolve one connection, mapping legacy agents by their model prefix."""
    selected = connection_id or "legacy"
    if selected == "legacy":
        prefixes = {
            "deepseek/": "deepseek-api",
            "openai/": "openai-api",
            "anthropic/": "anthropic-api",
            "gemini/": "gemini-api",
            "ollama/": "ollama-local",
        }
        selected = next(
            (mapped for prefix, mapped in prefixes.items() if model.startswith(prefix)),
            "legacy",
        )
    catalog = {item.id: item for item in connection_catalog(settings)}
    try:
        return catalog[selected]
    except KeyError as error:
        raise ModelConnectionError(f"unknown model connection: {connection_id}") from error


def validate_connection_model(
    connection_id: str,
    model: str,
    *,
    settings: Settings | None = None,
    require_configured: bool = False,
) -> ConnectionDescriptor:
    if not MODEL_PATTERN.fullmatch(model):
        raise ModelConnectionError("model id contains unsupported characters")
    connection = get_connection(connection_id, model=model, settings=settings)
    prefixes = {
        "deepseek-api": "deepseek/",
        "openai-api": "openai/",
        "anthropic-api": "anthropic/",
        "gemini-api": "gemini/",
        "ollama-local": "ollama/",
        "custom-openai": "openai/",
    }
    expected = prefixes.get(connection.id)
    if expected and not model.startswith(expected):
        raise ModelConnectionError(
            f"{connection.name} model ids must start with {expected!r}"
        )
    if require_configured and not connection.configured:
        raise ModelConnectionError(f"{connection.name} is not configured: {connection.setup}")
    return connection


def execution_connection(
    connection_id: str,
    model: str,
    *,
    settings: Settings | None = None,
    require_configured: bool = False,
) -> ConnectionDescriptor:
    """Return the route that will actually execute a research turn.

    An agent's selected route remains on its duty card, but global mock mode is an
    execution override.  Returning the mock descriptor here keeps run snapshots and
    model-call provenance truthful instead of recording an API route that was never
    contacted.
    """
    configured = settings or get_settings()
    validate_connection_model(
        connection_id,
        model,
        settings=configured,
        require_configured=require_configured,
    )
    if configured.mock_llm:
        return get_connection("mock", model="mock/research", settings=configured)
    return get_connection(connection_id, model=model, settings=configured)
