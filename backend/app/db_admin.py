"""Command-line database backup, verification, migration, and restore tools."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlmodel import create_engine

from app.database_maintenance import (
    DatabaseLock,
    DatabaseMaintenanceError,
    create_backup,
    restore_database,
    verify_database,
)
from app.database_migrations import upgrade_database
from app.db import DB_PATH


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.db_admin",
        description="Safely maintain Lemma's local SQLite database.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create a consistent, verified backup")
    backup.add_argument("--database", type=_path, default=DB_PATH)
    backup.add_argument("--output", type=_path)

    verify = commands.add_parser("verify", help="verify SQLite integrity and backup checksum")
    verify.add_argument("backup", type=_path)
    verify.add_argument(
        "--require-metadata",
        action="store_true",
        help="fail unless the matching Lemma checksum sidecar is present",
    )

    migrate = commands.add_parser("migrate", help="backup and upgrade to migration head")
    migrate.add_argument("--database", type=_path, default=DB_PATH)

    restore = commands.add_parser("restore", help="restore a verified Lemma backup")
    restore.add_argument("backup", type=_path)
    restore.add_argument("--database", type=_path, default=DB_PATH)
    restore.add_argument(
        "--yes",
        action="store_true",
        help="confirm replacement of the target database",
    )
    return parser


def _json_ready(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            # SQLite's online backup API is transactionally consistent while the
            # app is running, so read-only backups do not take the runtime lock.
            result = create_backup(args.database, destination=args.output)
            payload = asdict(result)
        elif args.command == "verify":
            payload = asdict(
                verify_database(args.backup, require_metadata=args.require_metadata)
            )
        elif args.command == "migrate":
            database = args.database.resolve()
            engine = create_engine(
                f"sqlite:///{database}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            with DatabaseLock.acquire(database):
                payload = asdict(upgrade_database(engine, database))
        else:
            if not args.yes:
                raise DatabaseMaintenanceError(
                    "restore replaces the live database; rerun with --yes after stopping Lemma"
                )
            previous = restore_database(args.backup, args.database)
            payload = {
                "restored": str(args.database),
                "pre_restore_backup": asdict(previous) if previous else None,
            }
    except DatabaseMaintenanceError as error:
        sys.stderr.write(f"error: {error}\n")
        return 2

    sys.stdout.write(json.dumps(payload, default=_json_ready, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
