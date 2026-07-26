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

    # 前端静态导出目录（Next.js output:export 产物 out/）。
    # 留空时按代码布局自动解析：仓库根/frontend/out 或容器内 /app/frontend/out。
    frontend_dist: str = ""
    # 子路径部署时的挂载前缀（对应前端构建期 NEXT_PUBLIC_BASE_PATH），如 "/options"。
    frontend_base_path: str = ""

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

    # 手动 ETL 触发（POST /api/etl/run）的管理口令。
    # 配置后该端点必须带 X-Admin-Token 头匹配才放行；留空则放行（仅适合本地
    # 开发）。公网部署务必设置，否则任何访客都能触发 ETL 烧 Deribit API 配额。
    admin_token: str = ""

    # Telegram Bot 推送（ETL 完成后自动推 top 策略 + 异常警报）。
    # 两项都配置才启用；留空则静默跳过。
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Telegram 推送语言：zh-CN / zh-TW / en
    telegram_lang: str = "zh-CN"

    # IP 地理位置识别（/api/geo 端点，用于前端多语言自动识别）。
    # geo_enabled=False 时直接返回默认语言，不调外部 API。
    geo_enabled: bool = True
    geo_default_lang: str = "zh-CN"
    geo_ipapi_url: str = "http://ip-api.com/json"


settings = Settings()
