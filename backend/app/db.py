# ─────────────────────────────────────────────────────────────────────────────
# db.py — the SQLite engine and how we open sessions to it.
# READING ORDER: backend #17
#
# WHAT THIS FILE DOES: creates ONE database engine pointed at backend/data/app.db,
# applies versioned migrations, and hands out short-lived Sessions for reads/writes.
#
# WHY SQLite + one file: this is a single-user local app. A file-based database needs
# no server to run, is trivial to inspect, and is easy to delete-and-recreate while
# learning. The data/ dir is gitignored and upgrades are backed up automatically.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, create_engine

from app.database_maintenance import DatabaseLock
from app.database_migrations import upgrade_database
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

# Held for the process lifetime after init_db(). The restore CLI takes the same
# advisory lock, so it cannot replace a database underneath a running backend.
_runtime_lock: DatabaseLock | None = None


@event.listens_for(engine, "connect")
def _configure_sqlite(connection, _record) -> None:
    """Enable integrity and concurrency settings on every SQLite connection."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()


def init_db() -> None:
    """Create the data directory and migrate the database to the current schema.

    Existing pre-Alembic databases are adopted by the baseline migration. Any
    non-empty database with pending revisions gets a verified online backup first.
    """
    global _runtime_lock

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

    acquired_here = False
    if _runtime_lock is None:
        _runtime_lock = DatabaseLock.acquire(DB_PATH)
        acquired_here = True
    try:
        result = upgrade_database(engine, DB_PATH)
    except Exception:
        if acquired_here and _runtime_lock is not None:
            _runtime_lock.release()
            _runtime_lock = None
        raise
    if DB_PATH.exists():
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            logger.warning("could not restrict database file permissions")
    if result.upgraded:
        logger.info(
            "database migrated from %s to %s",
            result.previous_revisions or ("legacy",),
            result.current_revisions,
        )
    logger.info("database ready at %s (revision %s)", DB_PATH, result.current_revisions)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a database Session and close it afterward (even on error).

    Exists so callers write `with get_session() as db: ...` and never leak a session.
    """
    with Session(engine) as session:
        yield session
