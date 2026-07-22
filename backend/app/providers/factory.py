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

from app.providers.base import ModelProvider
from app.providers.mock_provider import MockProvider
from app.settings import Settings

logger = logging.getLogger("aicompany.providers")


def get_provider(settings: Settings) -> ModelProvider:
    """Return the ModelProvider implied by settings (mock vs. live).

    Exists as the single decision point for provider selection. We import the real
    provider lazily (inside the function) so mock-mode runs never even import
    LiteLLM's heavier dependency tree.
    """
    if settings.mock_llm:
        logger.debug("using MockProvider (MOCK_LLM=true)")
        return MockProvider()

    # Imported here, not at module top, so mock mode has zero LiteLLM import cost.
    from app.providers.litellm_provider import LiteLLMProvider

    logger.debug("using LiteLLMProvider (MOCK_LLM=false)")
    return LiteLLMProvider()
