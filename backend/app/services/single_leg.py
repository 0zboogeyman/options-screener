from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .bs import delta_call_vec, delta_put_vec
from .preprocessing import prep_chain

logger = logging.getLogger(__name__)

# 综合评分低于该阈值的候选直接不展示（需求：评分 45 分以下的策略过滤掉）
MIN_SCORE = 45.0

# 综合评分权重（字段, 权重, 是否取反后再归一）。两策略权重结构一致，
# 仅参与字段不同；调整策略偏好时只需改这里。
CSP_SCORE_WEIGHTS: Tuple[Tuple[str, float, bool], ...] = (
    ("apr", 0.35, False),
    ("discount_pct", 0.25, False),
    ("assign_prob", 0.20, True),
    ("liquidity_score", 0.20, False),
)
CC_SCORE_WEIGHTS: Tuple[Tuple[str, float, bool], ...] = (
    ("apr_notional", 0.35, False),
    ("upside_pct", 0.25, False),
    ("assign_prob", 0.20, True),
    ("liquidity_score", 0.20, False),
)


def _normalize_score(values: List[float]) -> List[float]:
    if not values or len(values) == 0:
        return []

    arr = np.array(values)
    valid_mask = np.isfinite(arr)

    if not np.any(valid_mask):
        return [0.0] * len(values)

    valid_values = arr[valid_mask]
    min_val = np.min(valid_values)
    max_val = np.max(valid_values)

    if max_val == min_val:
        return [0.5 if np.isfinite(v) else 0.0 for v in values]

    return [((v - min_val) / (max_val - min_val)) if np.isfinite(v) else 0.0 for v in values]


def _empty_single_result(meta, df: pd.DataFrame, strategy: str, **extra) -> Dict:
    base = df["base"].iloc[0] if not df.empty else ""
    return {
        "asof_date": meta.date,
        "asof_ts": int(meta.asof_ts),
        "base": base,
        "spot_price": meta.spot_price,
        "strategy": strategy,
        "candidates": [],
        **extra,
    }


def _filter_chain(chain_df: pd.DataFrame, meta, option_type: str,
                  max_dte: int, min_oi: int, max_spread_bps: int) -> Tuple[pd.DataFrame, int]:
    """CSP/CC 共用过滤流水线：类型 → mid 有效 → DTE 范围 → 最小 OI → 最大点差。"""
    asof = int(meta.asof_ts)
    df = prep_chain(chain_df)
    df = df[df["option_type"].str.upper() == option_type].copy()
    df = df[df["mid"].notna()].copy()

    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    df = df[(df["dte"] <= max_dte) & (df["dte"] > 0)].copy()
    df = df[df["dte"] >= 1].copy()

    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()

    df["spread_bps"] = df["spread_ratio"] * 10000
    df = df[df["spread_bps"] <= max_spread_bps].copy()
    return df, asof


def _apply_scores(candidates: List[Dict],
                  weights: Tuple[Tuple[str, float, bool], ...]) -> None:
    """按 (字段, 权重, 取反) 规格对候选加权打分，结果写入 c["score"] 并原地降序排序；
    排序后过滤掉评分低于 MIN_SCORE 的候选（原地裁剪）。"""
    totals = [0.0] * len(candidates)
    for key, weight, invert in weights:
        raw = [(1.0 - c[key]) if invert else c[key] for c in candidates]
        norm = _normalize_score(raw)
        for i in range(len(candidates)):
            totals[i] += weight * norm[i]
    for i, c in enumerate(candidates):
        c["score"] = round(totals[i] * 100, 1)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates[:] = [c for c in candidates if c["score"] >= MIN_SCORE]


def scan_csp(
    chain_df: pd.DataFrame,
    meta,
    max_dte: int = 60,
    max_delta: float = 0.30,
    min_oi: int = 10,
    max_spread_bps: int = 500,
    available_cash: float = 10000,
    return_count: int = 20,
) -> Dict:
    spot = meta.spot_price
    df, asof = _filter_chain(chain_df, meta, "P", max_dte, min_oi, max_spread_bps)
    date = meta.date
    filters = {
        "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
        "max_spread_bps": max_spread_bps, "available_cash": available_cash,
    }

    if not spot:
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters=filters)
    if df.empty:
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters=filters)

    strikes = df["strike"].to_numpy(dtype=float)
    mids = df["mid"].to_numpy(dtype=float)
    dtes = df["dte"].to_numpy(dtype=float)
    ois = df["oi"].fillna(0).to_numpy(dtype=float)
    spread_bps = df["spread_bps"].to_numpy(dtype=float)
    instruments = df["instrument"].values
    expiry_ts = df["expiry_ts"].values
    quality_flags = df["quality_flag"].values

    if spot:
        iv = np.maximum(df["mark_iv"].fillna(0.5).to_numpy(dtype=float), 0.01)
        t_years = np.maximum(dtes / 365.0, 1e-6)
        delta_vec = delta_put_vec(spot, strikes, iv, t_years)
    else:
        delta_vec = np.zeros(len(df))
    assign_prob = np.abs(delta_vec)

    mask = (assign_prob <= max_delta) & (strikes <= available_cash)

    if not np.any(mask):
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters=filters)

    filtered_idx = np.where(mask)[0]

    premiums = mids * spot
    breakevens = strikes - premiums
    discount_pcts = (spot - breakevens) / spot
    aprs = np.where(strikes > 0, (premiums / strikes) * (365.0 / dtes), 0)
    liq_scores = np.log1p(ois) / (1 + spread_bps / 100)

    candidates = []
    for idx in filtered_idx:
        candidates.append({
            "symbol": instruments[idx],
            "expiry_ts": int(expiry_ts[idx]),
            "expiry_date": pd.Timestamp(expiry_ts[idx], unit="ms").strftime("%Y-%m-%d"),
            "strike": float(strikes[idx]),
            "delta": float(delta_vec[idx]),
            "premium": float(premiums[idx]),
            "breakeven": float(breakevens[idx]),
            "discount_pct": float(discount_pcts[idx]),
            "apr": float(aprs[idx]),
            "assign_prob": float(assign_prob[idx]),
            "oi": float(ois[idx]),
            "spread_bps": float(spread_bps[idx]),
            "dte": float(dtes[idx]),
            "liquidity_score": float(liq_scores[idx]),
            "quality": quality_flags[idx],
        })

    if not candidates:
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters=filters)

    _apply_scores(candidates, CSP_SCORE_WEIGHTS)
    top = candidates[:return_count]

    logger.info("CSP scan base=%s results=%d top_score=%.1f", df["base"].iloc[0], len(top), top[0]["score"] if top else 0)

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0],
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CSP",
        "filters": filters,
        "candidates": top,
    }


def scan_cc(
    chain_df: pd.DataFrame,
    meta,
    max_dte: int = 60,
    max_delta: float = 0.30,
    min_oi: int = 10,
    max_spread_bps: int = 500,
    position_size: int = 1,
    return_count: int = 20,
) -> Dict:
    spot = meta.spot_price
    df, asof = _filter_chain(chain_df, meta, "C", max_dte, min_oi, max_spread_bps)
    date = meta.date
    filters = {
        "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
        "max_spread_bps": max_spread_bps, "position_size": position_size,
    }

    if not spot:
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters=filters)
    if df.empty:
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters=filters)

    strikes = df["strike"].to_numpy(dtype=float)
    mids = df["mid"].to_numpy(dtype=float)
    dtes = df["dte"].to_numpy(dtype=float)
    ois = df["oi"].fillna(0).to_numpy(dtype=float)
    spread_bps = df["spread_bps"].to_numpy(dtype=float)
    instruments = df["instrument"].values
    expiry_ts = df["expiry_ts"].values
    quality_flags = df["quality_flag"].values

    if spot:
        iv = np.maximum(df["mark_iv"].fillna(0.5).to_numpy(dtype=float), 0.01)
        t_years = np.maximum(dtes / 365.0, 1e-6)
        delta_vec = delta_call_vec(spot, strikes, iv, t_years)
    else:
        delta_vec = np.zeros(len(df))

    mask = delta_vec <= max_delta

    if not np.any(mask):
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters=filters)

    filtered_idx = np.where(mask)[0]

    premiums = mids * spot * position_size
    upside_pcts = (strikes - spot) / spot
    notionals = spot * position_size
    aprs_notional = np.where(notionals > 0, (premiums / notionals) * (365.0 / dtes), 0)
    liq_scores = np.log1p(ois) / (1 + spread_bps / 100)

    candidates = []
    for idx in filtered_idx:
        candidates.append({
            "symbol": instruments[idx],
            "expiry_ts": int(expiry_ts[idx]),
            "expiry_date": pd.Timestamp(expiry_ts[idx], unit="ms").strftime("%Y-%m-%d"),
            "strike": float(strikes[idx]),
            "delta": float(delta_vec[idx]),
            "premium": float(premiums[idx]),
            "upside_pct": float(upside_pcts[idx]),
            "apr_notional": float(aprs_notional[idx]),
            "assign_prob": float(delta_vec[idx]),
            "oi": float(ois[idx]),
            "spread_bps": float(spread_bps[idx]),
            "dte": float(dtes[idx]),
            "liquidity_score": float(liq_scores[idx]),
            "quality": quality_flags[idx],
        })

    if not candidates:
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters=filters)

    _apply_scores(candidates, CC_SCORE_WEIGHTS)
    top = candidates[:return_count]

    logger.info("CC scan base=%s results=%d top_score=%.1f", df["base"].iloc[0], len(top), top[0]["score"] if top else 0)

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0],
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CC",
        "filters": filters,
        "candidates": top,
    }
