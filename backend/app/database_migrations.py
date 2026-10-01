"""Programmatic Alembic upgrades with pre-migration backup and schema validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect
from sqlalchemy.engine import URL
from sqlmodel import SQLModel

import app.models  # noqa: F401 -- register metadata for validation and autogeneration
from app.database_maintenance import BackupResult, DatabaseMaintenanceError, create_backup

logger = logging.getLogger("aicompany.db.migrations")
BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@dataclass(frozen=True)
class MigrationResult:
    """Summary of a startup schema check or upgrade."""

    previous_revisions: tuple[str, ...]
    current_revisions: tuple[str, ...]
    backup: BackupResult | None

    @property
    def upgraded(self) -> bool:
        return self.previous_revisions != self.current_revisions


def alembic_config(database_path: Path) -> Config:
    """Build an Alembic config for a specific Lemma SQLite database."""
    config = Config(str(ALEMBIC_INI))
    url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    # ConfigParser treats percent signs in paths as interpolation markers.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _state(engine: Engine, config: Config) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    scripts = ScriptDirectory.from_config(config)
    heads = tuple(sorted(scripts.get_heads()))
    if not heads:
        raise DatabaseMaintenanceError("the migration tree has no head revision")
    with engine.connect() as connection:
        current = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
        tables = set(inspect(connection).get_table_names())
    has_application_schema = bool(tables - {"alembic_version"})
    return current, heads, has_application_schema


def _validate_current_schema(engine: Engine) -> None:
    """Catch a stamped-but-incomplete schema before the API starts writing to it."""
    with engine.connect() as connection:
        inspector = inspect(connection)
        live_tables = set(inspector.get_table_names())
        expected_tables = set(SQLModel.metadata.tables)
        missing_tables = sorted(expected_tables - live_tables)
        if missing_tables:
            raise DatabaseMaintenanceError(
                f"database is missing migrated tables: {', '.join(missing_tables)}"
            )
        for name, table in SQLModel.metadata.tables.items():
            live_columns = {column["name"] for column in inspector.get_columns(name)}
            missing_columns = sorted(set(table.columns.keys()) - live_columns)
            if missing_columns:
                raise DatabaseMaintenanceError(
                    f"database table {name!r} is missing columns: {', '.join(missing_columns)}"
                )
        integrity = [str(row[0]) for row in connection.exec_driver_sql("PRAGMA quick_check")]
        if integrity != ["ok"]:
            raise DatabaseMaintenanceError(
                f"SQLite quick check failed after migration: {'; '.join(integrity)}"
            )


def upgrade_database(
    engine: Engine,
    database_path: Path,
    *,
    backup_dir: Path | None = None,
) -> MigrationResult:
    """Upgrade to the single Alembic head, backing up any existing schema first."""
    config = alembic_config(database_path)
    previous, heads, has_application_schema = _state(engine, config)
    pending = set(previous) != set(heads)
    backup: BackupResult | None = None

    if pending and database_path.exists() and has_application_schema:
        backup = create_backup(
            database_path,
            backup_dir=backup_dir or database_path.parent / "backups",
            reason=f"pre_migration:{','.join(previous) or 'legacy'}->{','.join(heads)}",
        )
        logger.info("verified pre-migration backup at %s", backup.path)

    if pending:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    current, final_heads, _ = _state(engine, config)
    if set(current) != set(final_heads):
        raise DatabaseMaintenanceError(
            f"database revision {current!r} does not match migration head {final_heads!r}"
        )
    _validate_current_schema(engine)
    return MigrationResult(previous, current, backup)
