from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.api.runs import RepoDep
from app.config import Settings, get_settings
from app.schemas.research import DocumentOut
from app.sources.documents import load_document
from app.sources.http import SourceError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile, repo: RepoDep, settings: Annotated[Settings, Depends(get_settings)]
) -> DocumentOut:
    """Upload a .txt or .md file to use as a source in a run (pass its id in document_ids)."""
    limit = settings.max_upload_bytes
    data = await file.read(limit + 1)  # never read more than the limit allows
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Document exceeds {limit} bytes")
    try:
        record = load_document(file.filename or "document.txt", data, max_bytes=limit)
    except SourceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return repo.save_document(record, record.title, data)
