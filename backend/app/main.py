from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_meta import router as meta_router
from .api.routes_spread import router as spread_router
from .api.routes_single_leg import router as single_leg_router


def create_app() -> FastAPI:
    app = FastAPI(title="Spread Finder API", version="0.1.0")

    # CORS: allow same-origin and dashboard/internal tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}
    # Duplicate health under subpath to work with reverse proxy that preserves subpath
    @app.get("/option-strategy-finder/api/health")
    def health_prefixed():
        return {"status": "ok"}

    # Register routers both at root and under "/option-strategy-finder" to support subpath deployment
    app.include_router(meta_router, prefix="/api")
    app.include_router(spread_router, prefix="/api")
    app.include_router(single_leg_router, prefix="/api")
    app.include_router(meta_router, prefix="/option-strategy-finder/api")
    app.include_router(spread_router, prefix="/option-strategy-finder/api")
    app.include_router(single_leg_router, prefix="/option-strategy-finder/api")

    return app


app = create_app()
