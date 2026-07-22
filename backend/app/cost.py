# ─────────────────────────────────────────────────────────────────────────────
# cost.py — turn token usage into money, persist it, and summarize the meter.
# READING ORDER: backend #18
#
# WHAT THIS FILE DOES:
#   Given a model and its token usage, it (1) prices the call from config.toml,
#   (2) saves a CostRecord row, and (3) returns the numbers the status-bar cost meter
#   shows: session totals and today's total. The caller then publishes a `cost_update`
#   event with this payload.
#
# WHY it returns a payload instead of publishing itself: keeping cost.py free of the
#   event bus keeps it a pure, testable unit. The route/orchestrator owns event
#   emission — a consistent separation across the codebase (providers do it too).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import select

from app.config import get_config
from app.db import get_session
from app.models import CostRecord
from app.providers.base import Usage

logger = logging.getLogger("aicompany.cost")


def estimate_usd(model: str, usage: Usage) -> float:
    """Price one completion in USD using the per-1M-token rates in config.toml.

    Exists as the one place pricing math lives. Unknown models price at $0 (with a
    warning) rather than crashing — a missing price shouldn't stop a turn.
    """
    pricing = get_config().pricing.get(model)
    if pricing is None:
        logger.warning("no price configured for model %r — counting it as $0", model)
        return 0.0
    input_cost = (usage.tokens_in / 1_000_000) * pricing.input
    output_cost = (usage.tokens_out / 1_000_000) * pricing.output
    return input_cost + output_cost


def _start_of_today_utc() -> datetime:
    """Return midnight UTC today — the lower bound for 'spent today'."""
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def record_and_summarize(session_id: str, model: str, usage: Usage) -> dict[str, float | int]:
    """Persist a priced CostRecord and return the current cost-meter numbers.

    Exists so a caller can do one call after a turn and get back exactly the
    `cost_update` payload: cumulative session tokens/cost plus today's total spend.
    """
    usd = estimate_usd(model, usage)

    with get_session() as db:
        db.add(
            CostRecord(
                session_id=session_id,
                model=model,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                usd=usd,
            )
        )
        db.commit()

        # Sum this session's spend so far (coalesce NULL → 0 for an empty result).
        session_row = db.exec(
            select(
                func.coalesce(func.sum(CostRecord.tokens_in), 0),
                func.coalesce(func.sum(CostRecord.tokens_out), 0),
                func.coalesce(func.sum(CostRecord.usd), 0.0),
            ).where(CostRecord.session_id == session_id)
        ).one()

        # Sum everything spent since midnight UTC for the "today" figure.
        day_usd = db.exec(
            select(func.coalesce(func.sum(CostRecord.usd), 0.0)).where(
                CostRecord.created_at >= _start_of_today_utc()
            )
        ).one()

    session_tokens_in, session_tokens_out, session_usd = session_row
    return {
        "session_tokens_in": int(session_tokens_in),
        "session_tokens_out": int(session_tokens_out),
        "session_usd": round(float(session_usd), 6),
        "day_usd": round(float(day_usd), 6),
    }
