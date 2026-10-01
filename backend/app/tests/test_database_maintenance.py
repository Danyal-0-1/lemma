"""Regression tests for migrations and loss-resistant SQLite maintenance."""

from __future__ import annotations

import json
import sqlite3
import stat
from pathlib import Path

import pytest
from alembic import command
from sqlmodel import create_engine

from app.database_maintenance import (
    DatabaseLock,
    DatabaseMaintenanceError,
    create_backup,
    restore_database,
    verify_database,
)
from app.database_migrations import alembic_config, upgrade_database


def _value(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT value FROM sample WHERE id = 1").fetchone()
    assert row is not None
    return str(row[0])


def _sample_database(path: Path, value: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO sample (id, value) VALUES (1, ?)", (value,))
    connection.commit()
    return connection


def test_online_backup_captures_wal_and_verifies_checksum(tmp_path: Path) -> None:
    source = tmp_path / "live.db"
    live_connection = _sample_database(source, "durable research")
    try:
        result = create_backup(source)
    finally:
        live_connection.close()

    assert _value(result.path) == "durable research"
    assert result.metadata_path.exists()
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["sha256"] == result.sha256
    assert metadata["reason"] == "manual"
    assert verify_database(result.path, require_metadata=True).metadata_verified

    with result.path.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(DatabaseMaintenanceError, match="metadata mismatch"):
        verify_database(result.path, require_metadata=True)


def test_restore_requires_verified_backup_and_preserves_current_database(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    _sample_database(source, "from backup").close()
    backup = create_backup(source)

    target = tmp_path / "target.db"
    _sample_database(target, "before restore").close()

    with DatabaseLock.acquire(target):
        with pytest.raises(DatabaseMaintenanceError, match="in use"):
            restore_database(backup.path, target)

    previous = restore_database(backup.path, target)
    assert previous is not None
    assert _value(target) == "from backup"
    assert _value(previous.path) == "before restore"
    assert verify_database(previous.path, require_metadata=True).metadata_verified


def test_migration_adopts_legacy_schema_with_backup_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE ideationsession (
                id VARCHAR NOT NULL PRIMARY KEY,
                title VARCHAR NOT NULL,
                seed_prompt VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                round INTEGER NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ideationsession
                (id, title, seed_prompt, status, round, created_at)
            VALUES ('legacy-1', 'Kept', 'Never delete me', 'approved', 2, '2026-01-01')
            """
        )

    engine = create_engine(f"sqlite:///{database}")
    first = upgrade_database(engine, database)
    assert first.upgraded
    assert first.backup is not None
    assert verify_database(first.backup.path, require_metadata=True).metadata_verified

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT seed_prompt FROM ideationsession WHERE id = 'legacy-1'"
        ).fetchone() == ("Never delete me",)
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision is not None
    assert revision[0] in first.current_revisions

    second = upgrade_database(engine, database)
    assert not second.upgraded
    assert second.backup is None
    engine.dispose()


def test_fresh_migration_does_not_create_empty_backup(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{database}")
    result = upgrade_database(engine, database)
    engine.dispose()

    assert result.upgraded
    assert result.backup is None
    assert not (tmp_path / "backups").exists()
    assert verify_database(database).revision in result.current_revisions


def test_0002_upgrades_populated_baseline_run_without_data_loss(tmp_path: Path) -> None:
    database = tmp_path / "baseline.db"
    engine = create_engine(f"sqlite:///{database}")
    config = alembic_config(database)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_current_schema")
        connection.exec_driver_sql(
            """
            INSERT INTO lab_projects
                (id, name, description, objective, status, created_at, updated_at)
            VALUES ('project-1', 'Existing project', '', 'Keep it', 'active',
                    '2026-01-01', '2026-01-01')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO lab_runs
                (id, kind, project_id, task_id, meeting_id, status, tokens_in,
                 tokens_out, error, started_at, completed_at)
            VALUES ('run-1', 'task', 'project-1', NULL, NULL, 'completed', 12,
                    34, NULL, '2026-01-01', '2026-01-01')
            """
        )

    result = upgrade_database(engine, database)
    with engine.connect() as connection:
        run = connection.exec_driver_sql(
            "SELECT attempt, retry_of_run_id, tokens_out FROM lab_runs WHERE id = 'run-1'"
        ).one()
        new_tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    engine.dispose()

    assert result.previous_revisions == ("0001_current_schema",)
    assert result.current_revisions == ("0004_research_assurance_hardening",)
    assert result.backup is not None
    assert run == (1, None, 34)
    assert {
        "lab_source_documents",
        "lab_claim_evidence",
        "lab_model_calls",
        "lab_evaluation_experiments",
        "lab_automation_runs",
        "lab_research_protocols",
        "lab_research_assurance_acceptances",
    } <= new_tables


def test_0004_repairs_early_0003_assurance_shape(tmp_path: Path) -> None:
    database = tmp_path / "early-0003.db"
    engine = create_engine(f"sqlite:///{database}")
    config = alembic_config(database)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003_research_assurance")
        connection.exec_driver_sql("DROP INDEX ix_lab_runs_input_sha256")
        connection.exec_driver_sql("ALTER TABLE lab_runs DROP COLUMN input_sha256")
        connection.exec_driver_sql("ALTER TABLE lab_runs DROP COLUMN input_snapshot")
        connection.exec_driver_sql(
            "ALTER TABLE lab_research_assurance_acceptances DROP COLUMN snapshot_json"
        )
        connection.exec_driver_sql(
            "ALTER TABLE lab_research_assurance_acceptances DROP COLUMN confirmed_criteria"
        )

    result = upgrade_database(engine, database)
    with engine.connect() as connection:
        run_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(lab_runs)")
        }
        acceptance_columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(lab_research_assurance_acceptances)"
            )
        }
    engine.dispose()

    assert result.previous_revisions == ("0003_research_assurance",)
    assert result.current_revisions == ("0004_research_assurance_hardening",)
    assert {"input_snapshot", "input_sha256"} <= run_columns
    assert {"snapshot_json", "confirmed_criteria"} <= acceptance_columns
