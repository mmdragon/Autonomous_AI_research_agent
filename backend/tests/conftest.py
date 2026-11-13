from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.sqlite3",
        sources_mode="fixtures",
    )


@pytest.fixture
def client(settings) -> Iterator[TestClient]:
    # The context manager runs the lifespan, which creates the database.
    with TestClient(create_app(settings)) as c:
        yield c
