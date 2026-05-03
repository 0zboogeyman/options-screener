"""
单腿策略 API 路由：CSP 和 CC
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.loader import load_chain_for, get_latest_date
from ..services.single_leg import scan_csp, scan_cc


class CSPRequest(BaseModel):
    """CSP（现金备兑接货）请求参数"""
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    max_dte: int = Field(default=60, ge=1, le=180, description="最大到期天数")
    max_delta: float = Field(default=0.30, ge=0.01, le=0.99, description="最大Delta绝对值")
    min_oi: int = Field(default=10, ge=0, description="最小持仓量")
    max_spread_bps: int = Field(default=500, ge=1, le=10000, description="最大点差（基点）")
    available_cash: float = Field(default=10000, gt=0, description="可用保证金（USD）")
    return_count: int = Field(default=20, ge=1, le=100, description="返回结果数量")


class CCRequest(BaseModel):
    """CC（现货备兑抛货）请求参数"""
    base: str = Field(..., pattern=r"^(BTC|ETH)$")
    max_dte: int = Field(default=60, ge=1, le=180, description="最大到期天数")
    max_delta: float = Field(default=0.30, ge=0.01, le=0.99, description="最大Delta绝对值")
    min_oi: int = Field(default=10, ge=0, description="最小持仓量")
    max_spread_bps: int = Field(default=500, ge=1, le=10000, description="最大点差（基点）")
    position_size: int = Field(default=1, ge=1, le=100, description="持仓合约数量（张）")
    return_count: int = Field(default=20, ge=1, le=100, description="返回结果数量")


router = APIRouter()


@router.post("/strategy/csp")
def scan_csp_strategy(req: CSPRequest):
    """
    扫描 CSP（Cash Secured Put）策略

    策略说明：
    - 卖出看跌期权，目标以折扣价接货或赚取权利金
    - 需要现金保证金支持
    - 适合看涨或中性市场
    """
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
def scan_cc_strategy(req: CCRequest):
    """
    扫描 CC（Covered Call）策略

    策略说明：
    - 在持有现货基础上卖出看涨期权
    - 获取额外权利金收益
    - 适合震荡或温和上涨市场
    """
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
