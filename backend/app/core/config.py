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

    # 生产环境必须通过 CORS_ORIGINS 显式声明具体域名；
    # 默认为空列表（拒绝一切跨域请求），同源部署经 Caddy 转发无需 CORS。
    cors_origins: List[str] = []

    log_level: str = "INFO"

    etl_bases: List[str] = ["BTC", "ETH"]

    # 扫描端点限流。前端一次页面操作可能触发多个请求，默认 30/min
    # 保证正常交互不触发 429，同时仍能挡住脚本化刷量。
    rate_limit_per_minute: str = "30/minute"

    # 是否开放 /docs、/redoc、/openapi.json，生产环境应保持关闭
    api_docs_enabled: bool = False

    graceful_shutdown_timeout: int = 15

    backup_retention_days: int = 7

    data_stale_hours: int = 25

    # ETL 自调度（容器内 supervisord 托管），支持:
    #   * ETL_SCHEDULE="HH:MM"    每天固定时刻跑（UTC）
    #   * ETL_SCHEDULE="@every Nh"  每 N 小时跑一次（例如 @every 6h）
    #   * ETL_SCHEDULE="off"        关闭调度，只跑首次启动的初始 ETL
    # 默认 08:05 UTC = 台北/北京时间 16:05（Deribit 每日 16:00 结算后 5 分钟抓数）
    etl_schedule: str = "08:05"


settings = Settings()
