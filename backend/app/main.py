from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import Settings, get_settings
from app.repositories.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(settings.database_path)
        yield

    app = FastAPI(
        title="Research Agent",
        version="0.1.0",
        description="Local-first research agent. Read-only retrieval from public sources.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
