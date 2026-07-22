# ─────────────────────────────────────────────────────────────────────────────
# config.py — load the non-secret, editable settings from config.toml.
# READING ORDER: backend #15  (teaches: tomllib + validating external files)
#
# WHAT THIS FILE DOES:
#   Parses backend/config.toml (role→model map, budget, per-model prices) into typed,
#   validated pydantic models. This is the COUNTERPART to settings.py: settings.py
#   holds secrets/paths from the environment; config.py holds shareable choices from
#   a committed file.
#
# WHY validate it: config.toml is hand-edited. Turning it into pydantic models means
#   a typo (a missing price, a string where a number belongs) fails loudly at startup
#   with a clear message, instead of causing a weird bug in the cost meter later.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import tomllib
from functools import lru_cache

from pydantic import BaseModel

from app.settings import BACKEND_DIR

# config.toml sits next to pyproject.toml at the backend root.
CONFIG_PATH = BACKEND_DIR / "config.toml"


class ModelPricing(BaseModel):
    """USD price per 1,000,000 tokens for one model (input and output separately)."""

    input: float
    output: float


class BudgetConfig(BaseModel):
    """Spending/round safety rails for an ideation session."""

    max_session_tokens: int
    max_rounds: int


class AppConfig(BaseModel):
    """The whole of config.toml, validated.

    Exists so callers read `get_config().roles["generator"]` with type safety instead
    of poking at a raw dict parsed from TOML.
    """

    # role name (e.g. "generator") -> LiteLLM model string (e.g. "deepseek/deepseek-chat")
    roles: dict[str, str]
    budget: BudgetConfig
    # model string -> its pricing. Used by the cost meter.
    pricing: dict[str, ModelPricing]


@lru_cache
def get_config() -> AppConfig:
    """Read and validate config.toml once, then return the cached AppConfig.

    Exists as the single entry point for crew configuration. lru_cache means the file
    is parsed on first use and reused thereafter (it doesn't change while running).
    """
    with CONFIG_PATH.open("rb") as file:  # tomllib requires binary mode
        raw = tomllib.load(file)
    return AppConfig.model_validate(raw)
