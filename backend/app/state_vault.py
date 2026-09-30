"""Automatic, reviewable Git snapshots of Lemma's durable application state.

The SQLite database remains the live transactional store.  This module writes a
deterministic JSON projection to a separate local Git repository so departments,
agents, tasks, meetings, findings, and ideation history have ordinary commit history.
Nothing is pushed automatically: adding a remote and publishing remain explicit human
actions in Source Control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlmodel import SQLModel, select

from app.db import get_session
from app.models import (
    ActivityRecord,
    Artifact,
    CostRecord,
    Department,
    Finding,
    IdeationSession,
    LabAgent,
    LabRun,
    MeetingMessage,
    Message,
    ResearchMeeting,
    ResearchProject,
    ResearchTask,
    TaskResult,
    Workspace,
)
from app.settings import get_settings
from app.workspaces.gitutil import git_capture, git_run

logger = logging.getLogger("aicompany.state_vault")

VAULT_FORMAT = "lemma-state-v1"
SNAPSHOT_FILE = "lemma-state.json"
README_FILE = "README.md"
GITIGNORE_FILE = ".gitignore"
SYNC_INTERVAL_SECONDS = 4.0

_README = """# Lemma state vault

This local Git repository is maintained by Lemma. `lemma-state.json` is a deterministic,
reviewable export of the application's durable R&D and ideation state. The live database
remains the source used while Lemma is running.

No provider API keys or Git credentials are exported. Research prompts and findings may
still be confidential, so review changes before adding a remote or pushing this repository.
Lemma never pushes this vault automatically.
"""

_GITIGNORE = "*.tmp\n*.lock\n.DS_Store\n"
_MODELS: tuple[tuple[str, type[SQLModel]], ...] = (
    ("ideation_sessions", IdeationSession),
    ("messages", Message),
    ("artifacts", Artifact),
    ("workspaces", Workspace),
    ("cost_records", CostRecord),
    ("departments", Department),
    ("agents", LabAgent),
    ("projects", ResearchProject),
    ("tasks", ResearchTask),
    ("runs", LabRun),
    ("task_results", TaskResult),
    ("findings", Finding),
    ("meetings", ResearchMeeting),
    ("meeting_messages", MeetingMessage),
    ("activities", ActivityRecord),
)
_SECRET_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
}
_sync_lock = threading.Lock()


class StateVaultError(RuntimeError):
    """A safe failure while exporting or committing the local state vault."""


def vault_path() -> Path:
    """Return the canonical configured vault path."""
    return Path(os.path.expanduser(get_settings().git_vault_dir)).resolve()


def _sanitize(value: Any, key: str | None = None) -> Any:
    """Remove credential-shaped fields and machine-specific absolute workspace paths."""
    if key is not None and key.casefold().replace("-", "_") in _SECRET_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(item_key): _sanitize(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize(item) for item in value]
    return value


def _row_payload(row: SQLModel) -> dict[str, Any]:
    payload = row.model_dump(mode="json")
    if isinstance(row, Workspace):
        # Absolute home-directory paths are operational metadata, not research state.
        payload["path"] = Path(row.path).name
    return _sanitize(payload)


def build_snapshot() -> dict[str, Any]:
    """Read every durable table into a stable, diff-friendly JSON structure."""
    tables: dict[str, list[dict[str, Any]]] = {}
    with get_session() as session:
        for label, model in _MODELS:
            rows = [_row_payload(row) for row in session.exec(select(model))]
            rows.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
            tables[label] = rows
    return {"format": VAULT_FORMAT, "tables": tables}


def render_snapshot() -> str:
    """Render the current snapshot without a changing export timestamp."""
    return json.dumps(build_snapshot(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_private(path: Path, content: str) -> bool:
    """Atomically replace one vault file only when its content changed."""
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except FileNotFoundError:
        pass
    except OSError as error:
        raise StateVaultError(f"could not read {path.name}") from error

    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StateVaultError(f"could not write {path.name}") from error
    return True


def sync_vault(directory: Path | None = None) -> bool:
    """Write and locally commit a state snapshot; return whether a commit was made."""
    root = (directory or vault_path()).resolve()
    with _sync_lock:
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
        except OSError as error:
            raise StateVaultError("could not create the Git state vault") from error

        repository = git_capture(["rev-parse", "--is-inside-work-tree"], root, max_output_bytes=128)
        if repository.returncode != 0 or repository.output.strip() != "true":
            try:
                git_run(["init", "-q"], root)
            except Exception as error:  # subprocess errors become one safe boundary message
                raise StateVaultError("Git could not initialize the state vault") from error

        changed = any(
            (
                _write_private(root / README_FILE, _README),
                _write_private(root / GITIGNORE_FILE, _GITIGNORE),
                _write_private(root / SNAPSHOT_FILE, render_snapshot()),
            )
        )
        if not changed:
            return False

        try:
            git_run(["add", "--", README_FILE, GITIGNORE_FILE, SNAPSHOT_FILE], root)
            git_run(
                [
                    "-c",
                    "user.name=Lemma State Vault",
                    "-c",
                    "user.email=noreply@lemma.local",
                    "commit",
                    "--no-verify",
                    "--no-gpg-sign",
                    "-q",
                    "-m",
                    "chore(vault): snapshot Lemma state",
                ],
                root,
            )
        except Exception as error:
            raise StateVaultError("Git could not commit the state snapshot") from error
        return True


async def sync_loop(stop: asyncio.Event) -> None:
    """Periodically capture asynchronous runs as well as request-driven changes."""
    while not stop.is_set():
        try:
            committed = await asyncio.to_thread(sync_vault)
            if committed:
                logger.info("committed a local application-state snapshot")
        except Exception:
            # This is a durability aid, not the live database. A transient SQLite or
            # Git failure must not terminate the long-running background task.
            logger.exception("state vault sync failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=SYNC_INTERVAL_SECONDS)
        except TimeoutError:
            continue
