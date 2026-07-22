# ─────────────────────────────────────────────────────────────────────────────
# db.py — the SQLite engine and how we open sessions to it.
# READING ORDER: backend #17
#
# WHAT THIS FILE DOES: creates ONE database engine pointed at backend/data/app.db,
# knows how to create the tables, and hands out short-lived Sessions for reads/writes.
#
# WHY SQLite + one file: this is a single-user local app. A file-based database needs
# no server to run, is trivial to inspect, and is easy to delete-and-recreate while
# learning (there are no migrations in v1 — §8). The data/ dir is gitignored.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.settings import BACKEND_DIR

logger = logging.getLogger("aicompany.db")

# The database lives under backend/data/ (created on startup, gitignored).
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

# check_same_thread=False: FastAPI may touch the connection from different threads;
# SQLite's default single-thread guard would otherwise raise. Safe here because our
# writes are small and serialized.
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create the data directory and all tables if they don't exist yet.

    Exists to be called once at startup. Importing app.models here guarantees every
    table class is registered on SQLModel.metadata before we create_all().
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Import for its side effect: registering the table classes (CostRecord, …).
    import app.models  # noqa: F401  (imported to register tables, not to use here)

    SQLModel.metadata.create_all(engine)
    logger.info("database ready at %s", DB_PATH)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a database Session and close it afterward (even on error).

    Exists so callers write `with get_session() as db: ...` and never leak a session.
    """
    with Session(engine) as session:
        yield session
