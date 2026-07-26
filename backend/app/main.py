from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .api.routes_meta import router as meta_router
from .api.routes_etl import router as etl_router
from .api.routes_geo import router as geo_router
from .api.routes_multi_leg import router as multi_leg_router
from .api.routes_spread import router as spread_router
from .api.routes_single_leg import router as single_leg_router
from .core.config import settings
from .core.logging import setup_logging
from .core.ratelimit import limiter
from .services.loader import list_available_dates

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

# 健康检查用的日期列表缓存（目录 glob 有 IO，60s TTL 足够：
# 数据更新频率是每天一次 ETL）
_HEALTH_DATES_TTL_SEC = 60.0
_health_dates_cache: dict = {"ts": 0.0, "dates": []}


def _cached_available_dates() -> list:
    now = time.monotonic()
    if now - _health_dates_cache["ts"] > _HEALTH_DATES_TTL_SEC:
        _health_dates_cache["dates"] = list_available_dates()
        _health_dates_cache["ts"] = now
    return _health_dates_cache["dates"]


def _frontend_dist() -> Path:
    """前端静态导出目录。

    仓库布局: backend/app/main.py -> <repo>/frontend/out
    容器布局: /app/app/main.py     -> /app/frontend/out
    可用 FRONTEND_DIST 环境变量显式覆盖。

    注：容器内 main.py 位于 /app/app/main.py，三层 parent 到根目录 /，
    与仓库布局（backend/app/main.py 三层 parent 到 repo 根）层级不同，
    因此显式列出两个候选路径，返回首个存在的目录。
    """
    if settings.frontend_dist:
        return Path(settings.frontend_dist)
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "frontend" / "out",  # 仓库布局
        Path("/app/frontend/out"),  # 容器布局
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]  # 都不存在时返回仓库布局路径（触发 API-only 警告）


def create_app() -> FastAPI:
    docs_enabled = settings.api_docs_enabled
    app = FastAPI(
        title="Option Scanner API",
        version="0.2.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    cors_origins = settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s status=%d duration=%.1fms",
            request.method, request.url.path, response.status_code, duration,
        )
        return response

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error %s %s: %s", request.method, request.url.path, str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": str(exc) if settings.log_level.upper() == "DEBUG" else "An unexpected error occurred",
            },
        )

    @app.get("/api/health")
    def health():
        data_status = {}
        try:
            dates = _cached_available_dates()
            latest = dates[-1] if dates else None
            data_status["data_latest_date"] = latest
            if latest:
                try:
                    latest_dt = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age = datetime.now(timezone.utc) - latest_dt
                    data_status["data_age_hours"] = round(age.total_seconds() / 3600, 1)
                    data_status["data_stale"] = age > timedelta(hours=settings.data_stale_hours)
                except ValueError:
                    data_status["data_age_hours"] = None
                    data_status["data_stale"] = None
        except Exception:
            logger.warning("Health check: failed to read data status", exc_info=True)
            data_status["data_latest_date"] = None
        return {"status": "ok", **data_status}

    app.include_router(meta_router, prefix="/api")
    app.include_router(spread_router, prefix="/api")
    app.include_router(single_leg_router, prefix="/api")
    app.include_router(multi_leg_router, prefix="/api")
    app.include_router(etl_router, prefix="/api")
    app.include_router(geo_router, prefix="/api")

    # 前端静态导出（Next.js output:export）同源托管：
    # API 路由先注册先匹配，"/" 挂载只兜底页面与静态资源，/api/* 不受影响。
    # 目录不存在（如后端独立开发、前端尚未构建）时降级为纯 API 模式，不报错。
    dist = _frontend_dist()
    if dist.is_dir():
        mount_path = settings.frontend_base_path or "/"
        app.mount(mount_path, StaticFiles(directory=str(dist), html=True), name="frontend")
        logger.info("Serving frontend static export from %s at %s", dist, mount_path)
    else:
        logger.warning("Frontend dist %s not found; running in API-only mode", dist)

    logger.info("Application initialized with %d routers", 6)
    return app


app = create_app()
