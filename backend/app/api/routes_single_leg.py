from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.ratelimit import limiter
from ..services.loader import load_chain_for, get_latest_date
from ..services.single_leg import scan_csp, scan_cc


class CSPRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    max_dte: int = Field(default=60, ge=1, le=180, description="最大到期天数")
    max_delta: float = Field(default=0.30, ge=0.01, le=0.99, description="最大Delta绝对值")
    min_oi: int = Field(default=10, ge=0, description="最小持仓量")
    max_spread_bps: int = Field(default=1500, ge=1, le=10000, description="最大点差（基点）")
    available_cash: float = Field(default=100000, gt=0, description="可用保证金（USD）")
    return_count: int = Field(default=20, ge=1, le=100, description="返回结果数量")


class CCRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    max_dte: int = Field(default=60, ge=1, le=180, description="最大到期天数")
    max_delta: float = Field(default=0.30, ge=0.01, le=0.99, description="最大Delta绝对值")
    min_oi: int = Field(default=10, ge=0, description="最小持仓量")
    max_spread_bps: int = Field(default=1500, ge=1, le=10000, description="最大点差（基点）")
    position_size: int = Field(default=1, ge=1, le=100, description="持仓合约数量（张）")
    return_count: int = Field(default=20, ge=1, le=100, description="返回结果数量")


router = APIRouter()


@router.post("/strategy/csp")
@limiter.limit(settings.rate_limit_per_minute)
def scan_csp_strategy(request: Request, req: CSPRequest):
    try:
        latest_date = get_latest_date()
        chain, meta = load_chain_for(date=latest_date, base=req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="数据不可用")

    result = scan_csp(
        chain_df=chain,
        meta=meta,
        max_dte=req.max_dte,
        max_delta=req.max_delta,
        min_oi=req.min_oi,
        max_spread_bps=req.max_spread_bps,
        available_cash=req.available_cash,
        return_count=req.return_count,
    )
    return result


@router.post("/strategy/cc")
@limiter.limit(settings.rate_limit_per_minute)
def scan_cc_strategy(request: Request, req: CCRequest):
    try:
        latest_date = get_latest_date()
        chain, meta = load_chain_for(date=latest_date, base=req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="数据不可用")

    result = scan_cc(
        chain_df=chain,
        meta=meta,
        max_dte=req.max_dte,
        max_delta=req.max_delta,
        min_oi=req.min_oi,
        max_spread_bps=req.max_spread_bps,
        position_size=req.position_size,
        return_count=req.return_count,
    )
    return result
