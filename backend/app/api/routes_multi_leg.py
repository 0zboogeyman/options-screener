"""多腿策略 API 端点：铁秃鹰 / 宽跨 / 日历价差 + 波动率面板。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from ..core.config import settings
from ..core.ratelimit import limiter
from ..services.loader import get_latest_date, load_chain_for
from ..services.multi_leg import scan_iron_condor, scan_strangle, scan_calendar
from ..services.vol_history import (
    current_iv_metrics,
    load_svi_surface,
    load_svi_history,
    load_dvol_history,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class IronCondorRequest(BaseModel):
    base: str = Field(..., pattern=settings.base_pattern)
    dte_min: int = Field(default=14, ge=1, le=180)
    dte_max: int = Field(default=60, ge=1, le=365)
    short_delta_min: float = Field(default=0.10, ge=0.01, le=0.50)
    short_delta_max: float = Field(default=0.25, ge=0.01, le=0.80)
    max_wing_steps: int = Field(default=5, ge=1, le=20)
    min_credit_usd: float = Field(default=20.0, ge=0)
    min_oi: int = Field(default=10, ge=0)
    pricing_mode: str = Field(default="mid", pattern=r"^(mid|conservative)$")
    return_count: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _check_ranges(self):
        if self.dte_min > self.dte_max:
            raise ValueError("dte_min must be <= dte_max")
        if self.short_delta_min > self.short_delta_max:
            raise ValueError("short_delta_min must be <= short_delta_max")
        return self


class StrangleRequest(BaseModel):
    base: str = Field(..., pattern=settings.base_pattern)
    side: str = Field(default="both", pattern=r"^(both|long|short)$")
    dte_min: int = Field(default=7, ge=1, le=180)
    dte_max: int = Field(default=45, ge=1, le=365)
    delta_min: float = Field(default=0.10, ge=0.01, le=0.50)
    delta_max: float = Field(default=0.30, ge=0.01, le=0.80)
    max_pool: int = Field(default=20, ge=3, le=50)
    min_oi: int = Field(default=10, ge=0)
    pricing_mode: str = Field(default="mid", pattern=r"^(mid|conservative)$")
    return_count: int = Field(default=15, ge=1, le=100)

    @model_validator(mode="after")
    def _check_ranges(self):
        if self.dte_min > self.dte_max:
            raise ValueError("dte_min must be <= dte_max")
        if self.delta_min > self.delta_max:
            raise ValueError("delta_min must be <= delta_max")
        return self


class CalendarRequest(BaseModel):
    base: str = Field(..., pattern=settings.base_pattern)
    near_dte_min: int = Field(default=7, ge=1, le=180)
    near_dte_max: int = Field(default=30, ge=1, le=365)
    min_gap_days: int = Field(default=14, ge=1, le=180)
    strike_band_pct: float = Field(default=0.10, ge=0.01, le=1.0)
    min_oi: int = Field(default=10, ge=0)
    pricing_mode: str = Field(default="mid", pattern=r"^(mid|conservative)$")
    return_count: int = Field(default=15, ge=1, le=100)

    @model_validator(mode="after")
    def _check_ranges(self):
        if self.near_dte_min > self.near_dte_max:
            raise ValueError("near_dte_min must be <= near_dte_max")
        return self


# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------


def _load_context(base: str):
    """加载最新日期的期权链 + SVI 曲面 + IVP。"""
    latest_date = get_latest_date()
    chain, meta = load_chain_for(date=latest_date, base=base)
    svi_surface = load_svi_surface(latest_date, base)
    iv_metrics = current_iv_metrics(base)
    ivp = iv_metrics.get("ivp")
    return latest_date, chain, meta, svi_surface, ivp


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("/strategy/iron-condor")
@limiter.limit(settings.rate_limit_per_minute)
def scan_iron_condor_strategy(request: Request, req: IronCondorRequest):
    try:
        _, chain, meta, svi_surface, ivp = _load_context(req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="数据不可用")

    result = scan_iron_condor(
        chain_df=chain,
        meta=meta,
        svi_surface=svi_surface,
        dte_min=req.dte_min,
        dte_max=req.dte_max,
        short_delta_min=req.short_delta_min,
        short_delta_max=req.short_delta_max,
        max_wing_steps=req.max_wing_steps,
        min_credit_usd=req.min_credit_usd,
        min_oi=req.min_oi,
        pricing_mode=req.pricing_mode,
        return_count=req.return_count,
        ivp=ivp,
    )
    return result


@router.post("/strategy/strangle")
@limiter.limit(settings.rate_limit_per_minute)
def scan_strangle_strategy(request: Request, req: StrangleRequest):
    try:
        _, chain, meta, svi_surface, ivp = _load_context(req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="数据不可用")

    result = scan_strangle(
        chain_df=chain,
        meta=meta,
        svi_surface=svi_surface,
        side=req.side,
        dte_min=req.dte_min,
        dte_max=req.dte_max,
        delta_min=req.delta_min,
        delta_max=req.delta_max,
        max_pool=req.max_pool,
        min_oi=req.min_oi,
        pricing_mode=req.pricing_mode,
        return_count=req.return_count,
        ivp=ivp,
    )
    return result


@router.post("/strategy/calendar")
@limiter.limit(settings.rate_limit_per_minute)
def scan_calendar_strategy(request: Request, req: CalendarRequest):
    try:
        _, chain, meta, svi_surface, ivp = _load_context(req.base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="数据不可用")

    result = scan_calendar(
        chain_df=chain,
        meta=meta,
        svi_surface=svi_surface,
        near_dte_min=req.near_dte_min,
        near_dte_max=req.near_dte_max,
        min_gap_days=req.min_gap_days,
        strike_band_pct=req.strike_band_pct,
        min_oi=req.min_oi,
        pricing_mode=req.pricing_mode,
        return_count=req.return_count,
        ivp=ivp,
    )
    return result


@router.get("/meta/vol")
@limiter.limit("60/minute")
def get_vol_panel(
    request: Request,
    base: str = Query(..., pattern=settings.base_pattern),
):
    """波动率面板：DVOL + IVP/IVR + SVI 期限结构 + skew。

    返回结构：
      dvol, ivp, ivr, days_available
      term_structure: [{expiry_ts, expiry_date, dte, atm_iv, rr25, bf25}]
      dvol_history: [{ts, close}] 最近 90 天
    """
    try:
        latest_date = get_latest_date()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="无数据")

    svi_surface = load_svi_surface(latest_date, base)
    iv_metrics = current_iv_metrics(base)

    term_structure: List[Dict[str, Any]] = []
    for exp_ts in sorted(svi_surface.keys()):
        p = svi_surface[exp_ts]
        dte = p.get("dte")
        if dte is None or dte <= 0:
            continue
        term_structure.append({
            "expiry_ts": int(exp_ts),
            "expiry_date": pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d"),
            "dte": round(float(dte), 1),
            "atm_iv": round(float(p["atm_iv"]), 4) if p.get("atm_iv") else None,
            "rr25": round(float(p["rr25"]), 4) if p.get("rr25") else None,
            "bf25": round(float(p["bf25"]), 4) if p.get("bf25") else None,
        })

    # DVOL 历史（最近 90 天，前端画趋势图）
    dvol_df = load_dvol_history(base)
    dvol_history: List[Dict[str, Any]] = []
    if not dvol_df.empty:
        recent = dvol_df.tail(90)
        for _, r in recent.iterrows():
            dvol_history.append({
                "ts": int(r["ts"]),
                "date": pd.Timestamp(int(r["ts"]), unit="ms").strftime("%Y-%m-%d"),
                "close": round(float(r["close"]), 2) if pd.notna(r.get("close")) else None,
            })

    return {
        "base": base,
        "date": latest_date,
        "dvol": iv_metrics.get("dvol"),
        "ivp": iv_metrics.get("ivp"),
        "ivr": iv_metrics.get("ivr"),
        "days_available": iv_metrics.get("days_available", 0),
        "term_structure": term_structure,
        "dvol_history": dvol_history,
    }
