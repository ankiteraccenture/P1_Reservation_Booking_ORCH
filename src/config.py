"""Application configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RSVN_", env_file=".env", extra="ignore")

    sqlite_path: str = Field(default="data/reservations.db")
    seed_file: str = Field(default="reservation_data.json")
    hold_ttl_minutes: int = 15
    hold_sweeper_interval_seconds: int = 10
    idempotency_window_hours: int = 24
    payment_timeout_seconds: float = 3.0
    payment_max_retries: int = 2
    payment_fail_rate: float = 0.0  # test/chaos hook
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent
