"""Local full-text indexing and retrieval for research artifacts."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from app.db import get_session
from app.lab import repo
from app.models import (
    Finding,
    MeetingMessage,
    ResearchClaim,
    ResearchMeeting,
    ResearchProject,
    ResearchTask,
    SourceDocument,
)

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


def _ensure_index(db: Any) -> None:
    db.exec(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS lab_search_index USING fts5(
                kind UNINDEXED,
                entity_id UNINDEXED,
                project_id UNINDEXED,
                title,
                body,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
    )


def refresh_project_index(project_id: str) -> int:
    """Rebuild one project's compact FTS index from canonical relational rows."""
    with get_session() as db:
        project = db.get(ResearchProject, project_id)
        if project is None:
            raise repo.LabNotFoundError("project not found")
        try:
            _ensure_index(db)
            db.exec(
                text("DELETE FROM lab_search_index WHERE project_id = :project_id"),
                params={"project_id": project_id},
            )
            documents: list[tuple[str, str, str, str]] = [
                ("project", project.id, project.name, f"{project.description}\n{project.objective}")
            ]
            documents.extend(
                (
                    "task",
                    row.id,
                    row.title,
                    f"{row.objective}\n{row.context}\n{row.expected_output}",
                )
                for row in db.exec(
                    select(ResearchTask).where(ResearchTask.project_id == project_id)
                )
            )
            documents.extend(
                ("finding", row.id, row.title, row.content)
                for row in db.exec(select(Finding).where(Finding.project_id == project_id))
            )
            documents.extend(
                ("source", row.id, row.title, f"{row.origin}\n{row.content}")
                for row in db.exec(
                    select(SourceDocument).where(
                        SourceDocument.project_id == project_id,
                        SourceDocument.status == "active",
                    )
                )
            )
            documents.extend(
                ("claim", row.id, "Research claim", row.statement)
                for row in db.exec(
                    select(ResearchClaim).where(ResearchClaim.project_id == project_id)
                )
            )
            meetings = list(
                db.exec(select(ResearchMeeting).where(ResearchMeeting.project_id == project_id))
            )
            documents.extend(("meeting", row.id, row.title, row.agenda) for row in meetings)
            meeting_ids = [meeting.id for meeting in meetings]
            if meeting_ids:
                documents.extend(
                    (
                        "meeting_message",
                        row.id,
                        f"Meeting {row.kind}",
                        row.content,
                    )
                    for row in db.exec(
                        select(MeetingMessage).where(MeetingMessage.meeting_id.in_(meeting_ids))
                    )
                )
            for kind, entity_id, title, body in documents:
                db.exec(
                    text(
                        """
                        INSERT INTO lab_search_index(kind, entity_id, project_id, title, body)
                        VALUES (:kind, :entity_id, :project_id, :title, :body)
                        """
                    ),
                    params={
                        "kind": kind,
                        "entity_id": entity_id,
                        "project_id": project_id,
                        "title": title,
                        "body": body,
                    },
                )
            db.commit()
            return len(documents)
        except OperationalError as error:
            db.rollback()
            raise repo.LabValidationError(
                "this SQLite build does not provide the required FTS5 search extension"
            ) from error


def _match_expression(query: str) -> str:
    tokens = _TOKEN_RE.findall(query.casefold())[:12]
    if not tokens:
        raise repo.LabValidationError("search query must include letters or numbers")
    # Quoting neutralizes FTS operators supplied by a browser request; prefix matching
    # keeps short domain terms useful without allowing arbitrary MATCH expressions.
    return " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)


def search(
    query: str,
    *,
    project_id: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 30,
) -> list[dict[str, object]]:
    """Return ranked local matches after synchronizing the selected project indexes."""
    kinds = kinds or []
    with get_session() as db:
        if project_id is not None:
            project_ids = [project_id]
        else:
            project_ids = list(db.exec(select(ResearchProject.id)))
    for selected_project_id in project_ids:
        refresh_project_index(selected_project_id)

    expression = _match_expression(query)
    filters = ["lab_search_index MATCH :expression"]
    params: dict[str, object] = {"expression": expression, "limit": limit}
    if project_id is not None:
        filters.append("project_id = :project_id")
        params["project_id"] = project_id
    if kinds:
        placeholders = []
        for index, kind in enumerate(kinds):
            key = f"kind_{index}"
            placeholders.append(f":{key}")
            params[key] = kind
        filters.append(f"kind IN ({', '.join(placeholders)})")
    statement = text(
        f"""
        SELECT kind, entity_id, project_id, title,
               snippet(lab_search_index, 4, '[', ']', ' … ', 28) AS snippet,
               bm25(lab_search_index, 2.0, 1.0) AS rank
        FROM lab_search_index
        WHERE {" AND ".join(filters)}
        ORDER BY rank
        LIMIT :limit
        """  # noqa: S608 - only fixed clauses/placeholders are interpolated
    )
    with get_session() as db:
        try:
            rows = db.exec(statement, params=params).mappings().all()
        except OperationalError as error:
            raise repo.LabValidationError("local full-text search is unavailable") from error
    return [
        {
            "kind": row["kind"],
            "entity_id": row["entity_id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "snippet": row["snippet"],
            "rank": float(row["rank"]),
        }
        for row in rows
    ]
