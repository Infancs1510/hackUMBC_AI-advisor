"""Application settings, read from environment variables and an optional .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    data_dir: Path = BASE_DIR / "data"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Used when the main model is over quota (429) or unavailable (500/503). Empty disables it.
    gemini_fallback_model: str | None = "gemini-3.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 30.0

    backboard_api_key: str | None = None
    backboard_base_url: str = "https://app.backboard.io/api"
    backboard_assistant_prefix: str = "hackumbc-advisor"
    backboard_timeout_seconds: float = 20.0

    # Comma-separated list of allowed CORS origins.
    frontend_origin: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
