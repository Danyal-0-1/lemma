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
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.settings import get_settings

logger = logging.getLogger("aicompany.db")

# Development defaults to backend/data. Installed builds override this with the
# private per-user XDG data directory through LEMMA_DATA_DIR.
DATA_DIR = Path(os.path.expanduser(get_settings().data_dir)).resolve()
DB_PATH = DATA_DIR / "app.db"

# check_same_thread=False: FastAPI may touch the connection from different threads;
# SQLite's default single-thread guard would otherwise raise. Safe here because our
# writes are small and serialized.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 10},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(connection, _record) -> None:
    """Enable integrity and concurrency settings on every SQLite connection."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()


def init_db() -> None:
    """Create the data directory and all tables if they don't exist yet.

    Exists to be called once at startup. Importing app.models here guarantees every
    table class is registered on SQLModel.metadata before we create_all().
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The database contains prompts, findings, and local paths. Keep it private even
    # if the user's umask is unusually permissive. chmod is best-effort on platforms
    # whose filesystems do not implement POSIX modes.
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        logger.warning("could not restrict database directory permissions")
    # Import for its side effect: registering the table classes (CostRecord, …).
    import app.models  # noqa: F401  (imported to register tables, not to use here)

    SQLModel.metadata.create_all(engine)
    if DB_PATH.exists():
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            logger.warning("could not restrict database file permissions")
    logger.info("database ready at %s", DB_PATH)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a database Session and close it afterward (even on error).

    Exists so callers write `with get_session() as db: ...` and never leak a session.
    """
    with Session(engine) as session:
        yield session
