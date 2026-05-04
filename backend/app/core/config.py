from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_root: Path = Path(__file__).parent.parent.parent / "data" / "parquet"

    deribit_api_url: str = "https://www.deribit.com/api/v2"

    cors_origins: List[str] = ["*"]

    log_level: str = "INFO"

    etl_bases: List[str] = ["BTC", "ETH"]

    rate_limit_per_minute: str = "10/minute"

    graceful_shutdown_timeout: int = 15

    backup_retention_days: int = 7

    data_stale_hours: int = 25


settings = Settings()
