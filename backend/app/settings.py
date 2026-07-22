# ─────────────────────────────────────────────────────────────────────────────
# settings.py — typed configuration for the whole backend.
# READING ORDER: backend #4  (teaches: pydantic-settings + the localhost guard)
#
# WHAT THIS FILE DOES:
#   Reads configuration from environment variables (and backend/.env) into ONE
#   validated, typed object — `Settings`. Every other module imports `get_settings()`
#   instead of touching os.environ directly, so there is a single, predictable place
#   where configuration lives and gets checked.
#
# HOW IT FITS:
#   main.py calls get_settings() at startup, runs the safety guards, and passes the
#   values down. Later milestones extend this class (config.toml parsing in M2, etc.).
#
# WHY pydantic-settings instead of reading os.environ by hand:
#   It gives us types (PORT becomes an int, MOCK_LLM becomes a real bool), defaults,
#   and validation for free — and it fails loudly at startup instead of deep in a
#   request when some value is the wrong shape.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The backend/ directory (this file is backend/app/settings.py → parent.parent = backend/).
# We resolve it absolutely so the .env file is found no matter what directory the
# process was launched from.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Host values we consider "safe" — they only accept connections from this machine.
# Binding anywhere else exposes a code-executing server to the network.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    """All backend configuration, validated once at startup.

    Exists so that configuration is typed, defaulted, and checked in a single place
    rather than scattered as raw os.environ lookups throughout the codebase.
    """

    # pydantic-settings reads backend/.env (via python-dotenv) and the process
    # environment. `extra="ignore"` means unknown keys in .env don't crash us —
    # useful because .env.example documents keys we don't consume until later milestones.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider keys (all optional; unused until M2) ---
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # --- Behaviour ---
    # Mock mode is ON by default: the app runs fully with zero keys and zero cost.
    mock_llm: bool = True

    # --- Server binding ---
    host: str = "127.0.0.1"
    port: int = 8000

    # Where build workspaces get created (M5). "~" is expanded lazily where used.
    workspaces_dir: str = "~/ai-company-workspaces"

    # --- Logging ---
    log_level: str = "INFO"

    # --- Escape hatch: allow a non-localhost HOST only when explicitly acknowledged. ---
    i_understand_the_risk: bool = False

    def has_any_key(self) -> bool:
        """True if at least one real provider key is configured.

        Used by the startup check that warns when MOCK_LLM=false but no key exists,
        so the user gets a clear message instead of a confusing 401 later.
        """
        return bool(self.deepseek_api_key or self.anthropic_api_key or self.openai_api_key)

    def assert_safe_binding(self) -> None:
        """Refuse to run on a non-localhost host unless the risk was acknowledged.

        Exists because this app spawns shells and runs commands; a network-exposed
        instance is a remote code execution service. We fail fast and loud rather
        than let that happen by accident.
        """
        if self.host in LOCAL_HOSTS:
            return
        if self.i_understand_the_risk:
            return
        raise RuntimeError(
            f"Refusing to bind to HOST={self.host!r}: this app executes shell commands, "
            f"so binding beyond localhost exposes a remote-code-execution surface. "
            f"Use HOST=127.0.0.1, or set I_UNDERSTAND_THE_RISK=true if you really mean it."
        )


@lru_cache
def get_settings() -> Settings:
    """Return the one shared Settings instance (built once, then cached).

    Exists so every module sees the same configuration object and we don't re-parse
    the environment on every call. lru_cache makes the first call build it and all
    later calls return the same instance.
    """
    return Settings()
