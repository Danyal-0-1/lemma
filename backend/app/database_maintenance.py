"""Consistent SQLite backups, integrity verification, restore, and process locking."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Lemma's packaged runtime is Linux-only
    fcntl = None  # type: ignore[assignment]

BACKUP_FORMAT_VERSION = 1
BUFFER_SIZE = 1024 * 1024


class DatabaseMaintenanceError(RuntimeError):
    """Raised when a database cannot be safely backed up, verified, or restored."""


@dataclass(frozen=True)
class BackupResult:
    """The two durable files created for one verified backup."""

    path: Path
    metadata_path: Path
    sha256: str
    size: int
    revision: str | None


@dataclass(frozen=True)
class VerificationResult:
    """Integrity and provenance details returned after verification."""

    path: Path
    sha256: str
    size: int
    revision: str | None
    metadata_verified: bool


@dataclass
class DatabaseLock:
    """An advisory lock shared by the running backend and restore command."""

    path: Path
    descriptor: int

    @classmethod
    def acquire(cls, database_path: Path, *, blocking: bool = False) -> DatabaseLock:
        if fcntl is None:
            raise DatabaseMaintenanceError(
                "safe database locking is unavailable on this platform"
            )
        database_path = _normalized_path(database_path)
        database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = database_path.with_name(f".{database_path.name}.lock")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            operation = fcntl.LOCK_EX
            if not blocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(descriptor, operation)
        except (BlockingIOError, OSError) as error:
            with suppress(UnboundLocalError):
                os.close(descriptor)
            raise DatabaseMaintenanceError(
                f"database is in use; stop Lemma before maintenance: {database_path}"
            ) from error
        return cls(path=lock_path, descriptor=descriptor)

    def release(self) -> None:
        if self.descriptor < 0:
            return
        assert fcntl is not None
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1

    def __enter__(self) -> DatabaseLock:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _normalized_path(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else (Path.cwd() / expanded).resolve()


def _require_regular_file(path: Path, *, label: str) -> Path:
    path = _normalized_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise DatabaseMaintenanceError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DatabaseMaintenanceError(f"{label} must be a regular, non-symlink file: {path}")
    return path


def _sqlite_uri(path: Path) -> str:
    return f"{path.as_uri()}?mode=ro"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(_sqlite_uri(path), uri=True, timeout=10)


def _integrity_and_revision(path: Path) -> str | None:
    try:
        with closing(_connect_readonly(path)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchall()
            messages = [str(row[0]) for row in result]
            if messages != ["ok"]:
                raise DatabaseMaintenanceError(
                    f"SQLite integrity check failed for {path}: {'; '.join(messages)}"
                )
            has_revision = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if not has_revision:
                return None
            revisions = [
                str(row[0])
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                ).fetchall()
            ]
            return ",".join(revisions) or None
    except sqlite3.Error as error:
        raise DatabaseMaintenanceError(f"cannot read SQLite database {path}: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_path(database_path: Path) -> Path:
    return database_path.with_name(f"{database_path.name}.json")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise DatabaseMaintenanceError(f"refusing to overwrite backup metadata: {path}")
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _snapshot(source: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with closing(_connect_readonly(source)) as source_connection:
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.commit()
        _integrity_and_revision(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        if destination.exists() or destination.is_symlink():
            raise DatabaseMaintenanceError(f"refusing to overwrite existing file: {destination}")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        _fsync_directory(destination.parent)
    except (sqlite3.Error, OSError) as error:
        raise DatabaseMaintenanceError(f"could not create SQLite snapshot: {error}") from error
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def create_backup(
    source: Path,
    *,
    backup_dir: Path | None = None,
    destination: Path | None = None,
    reason: str = "manual",
) -> BackupResult:
    """Create and verify a WAL-consistent SQLite snapshot plus checksum metadata."""
    source = _require_regular_file(source, label="database")
    _integrity_and_revision(source)

    if destination is not None and backup_dir is not None:
        raise DatabaseMaintenanceError("choose destination or backup_dir, not both")
    if destination is None:
        directory = _normalized_path(backup_dir or source.parent / "backups")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = directory / f"{source.stem}-{stamp}-{uuid4().hex[:8]}.db"
    else:
        destination = _normalized_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    if destination == source:
        raise DatabaseMaintenanceError("backup destination must differ from the live database")
    if destination.exists() or destination.is_symlink():
        raise DatabaseMaintenanceError(f"refusing to overwrite backup: {destination}")

    _snapshot(source, destination)
    revision = _integrity_and_revision(destination)
    checksum = _sha256(destination)
    size = destination.stat().st_size
    metadata_path = _metadata_path(destination)
    payload = {
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database_filename": source.name,
        "backup_filename": destination.name,
        "reason": reason,
        "sha256": checksum,
        "size": size,
        "alembic_revision": revision,
    }
    try:
        _write_json_atomic(metadata_path, payload)
        _fsync_directory(destination.parent)
    except Exception:
        with suppress(FileNotFoundError):
            destination.unlink()
        raise
    return BackupResult(destination, metadata_path, checksum, size, revision)


def verify_database(path: Path, *, require_metadata: bool = False) -> VerificationResult:
    """Run SQLite integrity checks and, when present, verify backup metadata."""
    path = _require_regular_file(path, label="database backup")
    revision = _integrity_and_revision(path)
    checksum = _sha256(path)
    size = path.stat().st_size
    metadata_path = _metadata_path(path)
    metadata_verified = False

    if metadata_path.exists() or metadata_path.is_symlink():
        metadata_path = _require_regular_file(metadata_path, label="backup metadata")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DatabaseMaintenanceError(f"invalid backup metadata: {metadata_path}") from error
        expected = {
            "format_version": BACKUP_FORMAT_VERSION,
            "backup_filename": path.name,
            "sha256": checksum,
            "size": size,
            "alembic_revision": revision,
        }
        mismatches = [key for key, value in expected.items() if metadata.get(key) != value]
        if mismatches:
            raise DatabaseMaintenanceError(
                f"backup metadata mismatch for {path}: {', '.join(mismatches)}"
            )
        metadata_verified = True
    elif require_metadata:
        raise DatabaseMaintenanceError(f"backup metadata is required: {metadata_path}")

    return VerificationResult(path, checksum, size, revision, metadata_verified)


def restore_database(
    backup: Path,
    target: Path,
    *,
    backup_dir: Path | None = None,
) -> BackupResult | None:
    """Atomically restore a verified backup, preserving the current DB first."""
    backup = _require_regular_file(backup, label="database backup")
    target = _normalized_path(target)
    if backup == target:
        raise DatabaseMaintenanceError("backup and restore target must differ")
    verify_database(backup, require_metadata=True)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    with DatabaseLock.acquire(target):
        previous: BackupResult | None = None
        if target.exists() or target.is_symlink():
            target = _require_regular_file(target, label="restore target")
            previous = create_backup(
                target,
                backup_dir=backup_dir or target.parent / "backups",
                reason="pre_restore",
            )

        staged = target.with_name(f".{target.name}.restore-{uuid4().hex}.tmp")
        try:
            _snapshot(backup, staged)
            verify_database(staged)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{target}{suffix}")
                if sidecar.exists() and not sidecar.is_symlink():
                    sidecar.unlink()
            os.replace(staged, target)
            os.chmod(target, 0o600)
            _fsync_directory(target.parent)
            verify_database(target)
        finally:
            with suppress(FileNotFoundError):
                staged.unlink()
    return previous
