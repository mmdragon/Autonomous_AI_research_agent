from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings, read from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    database_path: Path = BACKEND_ROOT / "data" / "research.sqlite3"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Only "mock" is implemented. No paid model API is called.
    llm_provider: Literal["mock"] = "mock"
    # "fixtures" replays recorded API responses (offline); "live" calls public APIs.
    sources_mode: Literal["fixtures", "live"] = "fixtures"
    fixtures_dir: Path = BACKEND_ROOT / "fixtures" / "http"

    # Wikimedia API etiquette requires a descriptive User-Agent with a contact.
    # Set your own contact in backend/.env before using live mode.
    http_user_agent: str = "research-agent-local/0.1 (contact not configured)"
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    http_min_interval_seconds: float = 1.0  # per host

    # Workflow limits
    max_steps_per_run: int = 12
    max_sources_per_question: int = 5
    max_sources_per_run: int = 25
    max_run_seconds: int = 300
    max_tool_calls_per_run: int = 60
    max_fetch_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
