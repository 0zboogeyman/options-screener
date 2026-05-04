from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .api.routes_meta import router as meta_router
from .api.routes_spread import router as spread_router
from .api.routes_single_leg import router as single_leg_router
from .core.config import settings
from .core.logging import setup_logging
from .services.loader import list_available_dates, get_latest_date

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


limiter = Limiter(key_func=get_remote_address)


def create_app() -> FastAPI:
    app = FastAPI(title="Spread Finder API", version="0.2.0")

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
                "detail": str(exc) if settings.log_level == "DEBUG" else "An unexpected error occurred",
            },
        )

    @app.get("/api/health")
    def health():
        data_status = {}
        try:
            dates = list_available_dates()
            latest = get_latest_date() if dates else None
            data_status["data_latest_date"] = latest
            if latest:
                from datetime import datetime as dt
                try:
                    latest_dt = dt.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age = dt.now(timezone.utc) - latest_dt
                    data_status["data_age_hours"] = round(age.total_seconds() / 3600, 1)
                    data_status["data_stale"] = age > timedelta(hours=settings.data_stale_hours)
                except ValueError:
                    data_status["data_age_hours"] = None
                    data_status["data_stale"] = None
        except Exception:
            data_status["data_latest_date"] = None
        return {"status": "ok", **data_status}

    app.include_router(meta_router, prefix="/api")
    app.include_router(spread_router, prefix="/api")
    app.include_router(single_leg_router, prefix="/api")

    logger.info("Application initialized with %d routers", 3)
    return app


app = create_app()
