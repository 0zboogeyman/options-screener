from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..core.ratelimit import limiter
from ..services.loader import list_available_dates, list_expiries_for, get_manifest


router = APIRouter()

# 元数据端点读操作成本较低，限流放宽但仍加保护，防止被脚本刷 IO
_META_RATE_LIMIT = "60/minute"


@router.get("/meta/dates")
@limiter.limit(_META_RATE_LIMIT)
def get_dates(request: Request):
    return {"dates": list_available_dates()}


@router.get("/expiries")
@limiter.limit(_META_RATE_LIMIT)
def get_expiries(
    request: Request,
    base: str = Query(..., pattern="^(BTC|ETH)$"),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
):
    try:
        expiries = list_expiries_for(date=date, base=base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="date/base not found")
    return {"date": date, "base": base, "expiries": expiries}


@router.get("/meta/asof")
@limiter.limit(_META_RATE_LIMIT)
def get_asof(
    request: Request,
    base: str = Query(..., pattern="^(BTC|ETH)$"),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
):
    try:
        manifest = get_manifest(date=date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="manifest not found for date")

    asof = manifest.get("asof_ts")
    expiries = manifest.get("expiries", {}).get(base, []) if manifest else []
    spot_prices = manifest.get("spot_prices", {})
    dvol_indices = manifest.get("dvol_indices", {})
    return {
        "date": date,
        "base": base,
        "asof_ts": asof,
        "expiries": expiries,
        "spot_price": spot_prices.get(base),
        "dvol_index": dvol_indices.get(base),
    }
