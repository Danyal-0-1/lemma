"""HTTP intake boundary for bounded, human-selected local research files."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.lab import repo, workflows
from app.lab.advanced_schemas import SourceCreate
from app.lab.source_import import MAX_SOURCE_UPLOAD_BYTES, extract_local_document

router = APIRouter(prefix="/api/lab", tags=["research-source-intake"])


def _translate(error: repo.LabError) -> HTTPException:
    if isinstance(error, repo.LabNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, repo.LabConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


@router.post("/sources/import-file", status_code=status.HTTP_201_CREATED)
async def import_source_file(
    project_id: Annotated[UUID, Form()],
    document: Annotated[UploadFile, File()],
    title: Annotated[str, Form(max_length=200)] = "",
) -> dict[str, Any]:
    """Capture a local text/PDF selection; agents never receive filesystem access."""
    # Starlette currently retains this metadata after close(), but capture it first so
    # extraction never depends on the lifetime of the temporary upload object.
    filename = document.filename or ""
    content_type = document.content_type
    try:
        payload = await document.read(MAX_SOURCE_UPLOAD_BYTES + 1)
    finally:
        await document.close()
    try:
        imported = await asyncio.to_thread(
            extract_local_document,
            filename,
            content_type,
            payload,
        )
        request = SourceCreate.model_validate(
            {
                "project_id": project_id,
                "title": title.strip() or imported.title,
                "source_type": "file",
                "origin": imported.origin,
                "content": imported.content,
                "metadata": imported.metadata,
            }
        )
        source = await asyncio.to_thread(
            workflows.create_source,
            request.model_dump(mode="json"),
        )
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    except repo.LabError as error:
        raise _translate(error) from error
    return source.model_dump(mode="json")
