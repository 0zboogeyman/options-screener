from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.loader import load_chain_for, get_latest_date
from ..services.scanner import scan_buckets, scan_opinion_spreads


class ScanRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    date: str = Field(..., description="YYYY-MM-DD")
    direction: str = Field(..., pattern=r"^(up|down)$")
    tenor: str = Field(..., pattern=r"^(near|mid|far)$")
    return_per_bucket: int = 3
    min_oi: int | None = Field(default=0)
    max_width: float | None = Field(default=None, description="max K2-K1 width in underlying units")


class OpinionRequest(BaseModel):
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    horizon: str = Field(..., pattern=r"^(short|mid|long)$", description="short: ≤1month, mid: 1-3months, long: ≥3months")
    view: str = Field(..., pattern=r"^(up|down|not_up|not_down)$", description="up/down: debit spread; not_up/not_down: credit spread")
    target_price: float = Field(..., gt=0, description="Target price in USD")
    max_gap_steps: int = Field(default=8, description="Max strike steps from anchor")
    return_per_bucket: int = Field(default=3, description="Top N strategies to return")


router = APIRouter()


@router.post("/spread/scan")
def scan(req: ScanRequest):
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
    )
    return result


@router.post("/spread/opinion")
def opinion(req: OpinionRequest):
    """
    根据用户观点（目标价 + 时间范围）筛选最优价差策略
    - up/down: 借方价差（付权利金）
    - not_up/not_down: 贷方价差（收权利金）
    """
    try:
        # 使用最新日期的数据
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

