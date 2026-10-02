# ─────────────────────────────────────────────────────────────────────────────
# factory.py — pick the right ModelProvider based on configuration.
# READING ORDER: backend #14
#
# WHAT THIS FILE DOES: one function, get_provider(), that returns the MockProvider
# when MOCK_LLM=true (the default) and the LiteLLMProvider otherwise. The rest of
# the app calls get_provider() and never has to know which one it got.
#
# WHY a factory: it puts the "which provider?" decision in exactly one place. Change
# the rule here and every caller follows — no scattered `if settings.mock_llm` checks.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.providers.base import ChatMessage, ModelProvider, StreamDone, TextDelta, Usage
from app.providers.connections import (
    ModelConnectionError,
    get_connection,
    validate_connection_model,
)
from app.providers.mock_provider import MockProvider
from app.settings import Settings

logger = logging.getLogger("aicompany.providers")


class _LegacyRoutingProvider:
    """Route older model-only callers by their explicit provider prefix."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def stream_chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator:
        connection = get_connection("legacy", model=model, settings=self._settings)
        if connection.id == "legacy":
            raise ModelConnectionError(
                "model prefix does not identify a configured provider; "
                "select an explicit model connection"
            )
        provider = get_provider(
            self._settings,
            connection.id,
            model,
            force_real=True,
        )
        async for event in provider.stream_chat(
            model,
            messages,
            max_output_tokens=max_output_tokens,
        ):
            yield event


def get_provider(
    settings: Settings,
    connection_id: str = "legacy",
    model: str = "",
    *,
    force_real: bool = False,
) -> ModelProvider:
    """Return the ModelProvider implied by settings (mock vs. live).

    Exists as the single decision point for provider selection. We import the real
    provider lazily (inside the function) so mock-mode runs never even import
    LiteLLM's heavier dependency tree.
    """
    if settings.mock_llm and not force_real:
        logger.debug("using MockProvider (MOCK_LLM=true)")
        return MockProvider()

    if connection_id == "legacy" and not model:
        return _LegacyRoutingProvider(settings)

    connection = get_connection(connection_id, model=model, settings=settings)
    if connection.id == "mock":
        return MockProvider()
    if not connection.configured:
        raise ModelConnectionError(f"{connection.name} is not configured: {connection.setup}")
    if connection.kind == "subscription":
        from app.providers.subscription_cli_provider import SubscriptionCLIProvider

        return SubscriptionCLIProvider(
            connection,
            timeout_seconds=settings.subscription_timeout_seconds,
        )

    # Imported here, not at module top, so mock mode has zero LiteLLM import cost.
    from app.providers.litellm_provider import LiteLLMProvider

    logger.debug("using LiteLLMProvider for %s (MOCK_LLM=false)", connection.id)
    return LiteLLMProvider(api_key=connection.api_key, api_base=connection.base_url)


async def test_connection(
    settings: Settings,
    connection_id: str,
    model: str,
) -> dict[str, object]:
    """Make one explicitly requested, tiny real call and return no credentials."""
    connection = validate_connection_model(
        connection_id,
        model,
        settings=settings,
        require_configured=True,
    )
    provider = get_provider(
        settings,
        connection.id,
        model,
        force_real=True,
    )
    usage = Usage()
    parts: list[str] = []
    messages = [
        ChatMessage(
            role="system",
            content="Return only the word connected. Do not use tools or external context.",
        ),
        ChatMessage(role="user", content="Connection test."),
    ]
    async for event in provider.stream_chat(model, messages, max_output_tokens=16):
        if isinstance(event, TextDelta):
            parts.append(event.text)
            if sum(len(part) for part in parts) > 4_000:
                raise RuntimeError("connection test response exceeded its limit")
        elif isinstance(event, StreamDone):
            usage = event.usage
    if not "".join(parts).strip():
        raise RuntimeError("model connection returned an empty response")
    return {
        "ok": True,
        "message": f"{connection.name} responded successfully.",
        "connection_id": connection.id,
        "model": model,
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
    }
