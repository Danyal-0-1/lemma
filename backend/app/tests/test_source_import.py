"""Tests for bounded, human-initiated local document extraction."""

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlmodel import SQLModel, create_engine

from app import db
from app.lab import repo
from app.lab.source_import import extract_local_document
from app.main import app


@pytest.fixture
def source_db(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source-import.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return engine


def test_import_utf8_text_records_raw_file_identity() -> None:
    imported = extract_local_document(
        "notes.md",
        "text/markdown",
        b"A measured result with a clear limitation.",
    )

    assert imported.title == "notes"
    assert imported.content.startswith("A measured result")
    assert imported.metadata["filename"] == "notes.md"
    assert imported.metadata["size_bytes"] == 42
    assert len(str(imported.metadata["file_sha256"])) == 64


def test_import_rejects_unsupported_or_non_utf8_documents() -> None:
    with pytest.raises(repo.LabValidationError, match="unsupported"):
        extract_local_document("archive.zip", "application/zip", b"not a research source")
    with pytest.raises(repo.LabValidationError, match="UTF-8"):
        extract_local_document("notes.txt", "text/plain", b"\xff\xfe")


def test_scanned_or_empty_pdf_requires_ocr() -> None:
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)

    with pytest.raises(repo.LabValidationError, match="OCR"):
        extract_local_document("scan.pdf", "application/pdf", stream.getvalue())


def test_import_endpoint_persists_human_selected_document(source_db) -> None:
    project = repo.create_project({"name": "Import study", "objective": "Check a result."})
    client = TestClient(app)
    try:
        response = client.post(
            "/api/lab/sources/import-file",
            headers={"Origin": "http://127.0.0.1:5173"},
            data={"project_id": project.id, "title": "Measured evidence"},
            files={
                "document": (
                    "evidence.md",
                    b"The bounded experiment measured a reproducible result.",
                    "text/markdown",
                )
            },
        )
    finally:
        client.close()

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Measured evidence"
    assert payload["source_type"] == "file"
    assert payload["metadata_json"]["filename"] == "evidence.md"
    assert len(payload["content_sha256"]) == 64
