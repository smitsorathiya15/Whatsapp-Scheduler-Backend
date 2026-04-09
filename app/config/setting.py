"""Application settings loaded from the project-root .env.{APP_ENV} file."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE = Path(__file__).resolve().parents[2]
_APP_ENV = os.getenv("APP_ENV", "dev")
_ENV_PATH = _BASE / f".env.{_APP_ENV}"


class Settings(BaseSettings):
    """Typed configuration container — all values sourced from .env file."""

    # ── Application ───────────────────────────────────────────
    APP_NAME: str
    APP_ENV: str
    DEBUG: bool

    # ── Database ──────────────────────────────────────────────
    DB_URL: str

    # ── JWT ───────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_ALGORITHM: str
    JWT_EXPIRES_MINUTES: int

    # ── WhatsApp ──────────────────────────────────────────────
    WA_PROFILE_DIR: str
    WA_HEADLESS: bool = True

    # ── Scheduler ─────────────────────────────────────────────
    SCHEDULER_INTERVAL_SECONDS: int
    SCHEDULER_TIMEZONE: str

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings: Settings = Settings()


def get_settings() -> Settings:
    """Return the singleton settings instance."""
    return settings


__all__ = ["Settings", "settings", "get_settings"]
