from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.ratelimit import limiter
from ..services.loader import load_chain_for, get_latest_date
from ..services.scanner import scan_buckets, scan_opinion_spreads


class ScanRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    direction: str = Field(..., pattern=r"^(up|down|both)$", description="up=仅CALL, down=仅PUT, both=全部（单次请求即可，推荐）")
    tenor: str = Field(..., pattern=r"^(near|mid|far)$")
    return_per_bucket: int = Field(default=3, ge=1, le=50)
    min_oi: int | None = Field(default=0, ge=0)
    max_width: float | None = Field(default=None, gt=0, description="max K2-K1 width in underlying units")
    max_gap_steps: int = Field(default=10, ge=1, le=100, description="两腿之间允许的最大行权价步数")


class OpinionRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    horizon: str = Field(..., pattern=r"^(short|mid|long)$", description="short: ≤1month, mid: 1-3months, long: ≥3months")
    view: str = Field(..., pattern=r"^(up|down|not_up|not_down)$", description="up/down: debit spread; not_up/not_down: credit spread")
    target_price: float = Field(..., gt=0, description="Target price in USD")
    max_gap_steps: int = Field(default=8, ge=1, le=50, description="Max strike steps from anchor")
    return_per_bucket: int = Field(default=3, ge=1, le=50, description="Top N strategies to return")


router = APIRouter()


@router.post("/spread/scan")
@limiter.limit(settings.rate_limit_per_minute)
def scan(request: Request, req: ScanRequest):
    try:
        chain, meta = load_chain_for(date=req.date, base=req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="data not found for date/base")

    result = scan_buckets(
        chain_df=chain,
        meta=meta,
        tenor=req.tenor,
        direction=req.direction,
        return_per_bucket=req.return_per_bucket,
        min_oi=req.min_oi or 0,
        max_width=req.max_width,
        max_gap_steps=req.max_gap_steps,
    )
    return result


@router.post("/spread/opinion")
@limiter.limit(settings.rate_limit_per_minute)
def opinion(request: Request, req: OpinionRequest):
    try:
        latest_date = get_latest_date()
        chain, meta = load_chain_for(date=latest_date, base=req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="data not found")

    result = scan_opinion_spreads(
        chain_df=chain,
        meta=meta,
        horizon=req.horizon,
        view=req.view,
        target_price=req.target_price,
        max_gap_steps=req.max_gap_steps,
        return_count=req.return_per_bucket,
    )
    return result
