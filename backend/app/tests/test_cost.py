# ─────────────────────────────────────────────────────────────────────────────
# test_cost.py — prove pricing math and the cost-meter summary.
# READING ORDER: backend #21  (teaches: monkeypatching a dependency for isolation)
#
# Two things matter for the cost meter: (1) tokens are priced correctly from
# config.toml, and (2) recording a call returns the right cumulative totals. We test
# the summary against a TEMPORARY database so the test never touches your real dev data.
# ─────────────────────────────────────────────────────────────────────────────

from sqlmodel import SQLModel, create_engine

from app import cost, db
from app.providers.base import Usage


def test_estimate_usd_prices_from_config() -> None:
    """A known model is priced from config.toml; an unknown one costs $0."""
    # config.toml: deepseek/deepseek-chat = { input = 0.28, output = 0.42 } per 1M tokens.
    usd = cost.estimate_usd(
        "deepseek/deepseek-chat", Usage(tokens_in=1_000_000, tokens_out=1_000_000)
    )
    assert round(usd, 6) == 0.70  # 0.28 (input) + 0.42 (output)

    # Unknown models must not crash — they price at zero.
    assert cost.estimate_usd("who/knows", Usage(tokens_in=1000, tokens_out=1000)) == 0.0


def test_record_and_summarize_accumulates(tmp_path, monkeypatch) -> None:
    """Recording calls returns cumulative session totals from a temp database."""
    # Point the db module at a throwaway SQLite file, then create the tables there.
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(db, "engine", test_engine)

    first = cost.record_and_summarize(
        "sess1", "deepseek/deepseek-chat", Usage(tokens_in=1000, tokens_out=2000)
    )
    assert first["session_tokens_in"] == 1000
    assert first["session_tokens_out"] == 2000
    assert first["session_usd"] > 0

    # A second call in the same session accumulates, not replaces.
    second = cost.record_and_summarize(
        "sess1", "deepseek/deepseek-chat", Usage(tokens_in=500, tokens_out=500)
    )
    assert second["session_tokens_in"] == 1500
    assert second["session_tokens_out"] == 2500
