"""Bounded extraction for human-selected local research documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from app.lab import repo

MAX_SOURCE_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_SOURCE_CONTENT_CHARS = 500_000
MAX_PDF_PAGES = 500

_TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".htm",
    ".json",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class ImportedSource:
    title: str
    origin: str
    content: str
    metadata: dict[str, object]


def _safe_filename(filename: str) -> str:
    normalized = Path(filename.replace("\\", "/")).name.strip()
    if not normalized or normalized in {".", ".."}:
        raise repo.LabValidationError("the uploaded document needs a valid filename")
    return normalized[:240]


def _bounded_content(content: str) -> str:
    if not content.strip():
        raise repo.LabValidationError("the imported document contains no extractable text")
    if len(content) > MAX_SOURCE_CONTENT_CHARS:
        raise repo.LabValidationError(
            "extracted document text exceeds the 500,000 character source limit"
        )
    return content


def _extract_pdf(payload: bytes) -> tuple[str, int]:
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
    except Exception as error:  # noqa: BLE001 - parser errors become safe validation messages
        raise repo.LabValidationError("the uploaded PDF could not be parsed") from error
    if reader.is_encrypted:
        raise repo.LabValidationError("encrypted PDFs must be unlocked before import")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise repo.LabValidationError(f"PDF import is limited to {MAX_PDF_PAGES} pages")

    sections: list[str] = []
    total_chars = 0
    try:
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            section = f"[PDF page {page_number}]\n{text}"
            total_chars += len(section) + 2
            if total_chars > MAX_SOURCE_CONTENT_CHARS:
                raise repo.LabValidationError(
                    "extracted PDF text exceeds the 500,000 character source limit"
                )
            sections.append(section)
    except repo.LabError:
        raise
    except Exception as error:  # noqa: BLE001 - parser internals are not browser-safe
        raise repo.LabValidationError("text extraction failed for the uploaded PDF") from error
    if not sections:
        raise repo.LabValidationError(
            "the PDF has no extractable text; run OCR first, then import the searchable PDF"
        )
    return "\n\n".join(sections), len(reader.pages)


def extract_local_document(
    filename: str,
    content_type: str | None,
    payload: bytes,
) -> ImportedSource:
    """Extract one explicitly selected file without network or filesystem access."""
    safe_name = _safe_filename(filename)
    if not payload:
        raise repo.LabValidationError("the uploaded document is empty")
    if len(payload) > MAX_SOURCE_UPLOAD_BYTES:
        raise repo.LabValidationError("document upload exceeds the 20 MiB limit")

    suffix = Path(safe_name).suffix.casefold()
    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    metadata: dict[str, object] = {
        "filename": safe_name,
        "media_type": normalized_type or "application/octet-stream",
        "size_bytes": len(payload),
        "file_sha256": hashlib.sha256(payload).hexdigest(),
        "intake": "human_selected_local_file",
    }
    if suffix == ".pdf" or normalized_type == "application/pdf":
        content, page_count = _extract_pdf(payload)
        metadata.update({"extractor": "pypdf", "page_count": page_count})
    elif suffix in _TEXT_SUFFIXES or normalized_type.startswith("text/"):
        try:
            content = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise repo.LabValidationError(
                "text documents must use UTF-8 encoding"
            ) from error
        content = _bounded_content(content)
        metadata["extractor"] = "utf-8"
    else:
        raise repo.LabValidationError(
            "unsupported document type; import PDF, Markdown, text, CSV, JSON, HTML, or XML"
        )

    title = Path(safe_name).stem.strip()[:200] or "Imported document"
    return ImportedSource(
        title=title,
        origin=f"local file: {safe_name}",
        content=content,
        metadata=metadata,
    )
