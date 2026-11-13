from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.repositories.db import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {
        "status": "ok",
        "database": "ok" if check_db(settings.database_path) else "unavailable",
        "llm_provider": settings.llm_provider,
        "sources_mode": settings.sources_mode,
    }
