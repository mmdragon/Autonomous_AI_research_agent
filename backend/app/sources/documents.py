"""Load a user-provided document as a source record. Text and Markdown only for now."""

from __future__ import annotations

from pathlib import PurePath

from app.sources.http import BlockedError, PermanentSourceError
from app.sources.models import SourceKind, SourceRecord
from app.sources.text import content_hash

ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown"}


def load_document(filename: str, data: bytes, *, max_bytes: int) -> SourceRecord:
    name = PurePath(filename).name  # drop any client-supplied directories
    suffix = PurePath(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise BlockedError(f"Unsupported document type {suffix or '(none)'}; allowed: {allowed}")
    if len(data) > max_bytes:
        raise BlockedError(f"Document exceeds {max_bytes} bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentSourceError("Document is not valid UTF-8 text") from exc
    if not text.strip():
        raise PermanentSourceError("Document is empty")
    # The URL identifies the exact bytes, so re-uploading the same file dedupes.
    return SourceRecord.build(
        url=f"upload://{content_hash(text)[:16]}/{name}",
        title=name,
        source_name="document",
        source_kind=SourceKind.DOCUMENT,
        content=text,
        metadata={"filename": name, "size_bytes": len(data)},
    )
