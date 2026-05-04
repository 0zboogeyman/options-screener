from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from .bs import delta_call, delta_put
from .preprocessing import prep_chain

logger = logging.getLogger(__name__)


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
    df = prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date
    spot = meta.spot_price

    df = df[df["option_type"].str.upper() == "P"].copy()
    df = df[df["mid"].notna()].copy()

    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    df = df[(df["dte"] <= max_dte) & (df["dte"] > 0)].copy()

    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()

    df["spread_bps"] = df["spread_ratio"] * 10000
    df = df[df["spread_bps"] <= max_spread_bps].copy()

    if df.empty:
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "available_cash": available_cash,
        })

    strikes = df["strike"].values.astype(float)
    mids = df["mid"].values.astype(float)
    dtes = df["dte"].values.astype(float)
    ois = df["oi"].fillna(0).values.astype(float)
    spread_bps = df["spread_bps"].values.astype(float)
    instruments = df["instrument"].values
    expiry_ts = df["expiry_ts"].values
    quality_flags = df["quality_flag"].values

    t_years = dtes / 365.0
    iv = df["mark_iv"].fillna(0.5).values.astype(float)

    delta_vec = np.array([delta_put(spot, k, max(v, 0.01), max(t, 1e-6)) if spot else 0.0 for k, v, t in zip(strikes, iv, t_years)])
    assign_prob = np.abs(delta_vec)

    mask = (
        (assign_prob <= max_delta) &
        (strikes <= available_cash)
    )

    if not np.any(mask):
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "available_cash": available_cash,
        })

    filtered_idx = np.where(mask)[0]

    premiums = mids * spot
    breakevens = strikes - mids
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
        return _empty_single_result(meta, df, "CSP", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "available_cash": available_cash,
        })

    c_aprs = [c["apr"] for c in candidates]
    c_discounts = [c["discount_pct"] for c in candidates]
    c_assign = [1.0 - c["assign_prob"] for c in candidates]
    c_liq = [c["liquidity_score"] for c in candidates]

    n_apr = _normalize_score(c_aprs)
    n_discount = _normalize_score(c_discounts)
    n_assign = _normalize_score(c_assign)
    n_liq = _normalize_score(c_liq)

    w_apr, w_buffer, w_assign, w_liq = 0.35, 0.25, 0.20, 0.20

    for i, c in enumerate(candidates):
        score = (w_apr * n_apr[i] + w_buffer * n_discount[i] + w_assign * n_assign[i] + w_liq * n_liq[i]) * 100
        c["score"] = round(score, 1)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:return_count]

    logger.info("CSP scan base=%s results=%d top_score=%.1f", df["base"].iloc[0], len(top), top[0]["score"] if top else 0)

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0],
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CSP",
        "filters": {
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "available_cash": available_cash,
        },
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
    df = prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date
    spot = meta.spot_price

    df = df[df["option_type"].str.upper() == "C"].copy()
    df = df[df["mid"].notna()].copy()

    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    df = df[(df["dte"] <= max_dte) & (df["dte"] > 0)].copy()

    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()

    df["spread_bps"] = df["spread_ratio"] * 10000
    df = df[df["spread_bps"] <= max_spread_bps].copy()

    if df.empty:
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "position_size": position_size,
        })

    strikes = df["strike"].values.astype(float)
    mids = df["mid"].values.astype(float)
    dtes = df["dte"].values.astype(float)
    ois = df["oi"].fillna(0).values.astype(float)
    spread_bps = df["spread_bps"].values.astype(float)
    instruments = df["instrument"].values
    expiry_ts = df["expiry_ts"].values
    quality_flags = df["quality_flag"].values

    t_years = dtes / 365.0
    iv = df["mark_iv"].fillna(0.5).values.astype(float)

    delta_vec = np.array([delta_call(spot, k, max(v, 0.01), max(t, 1e-6)) if spot else 0.0 for k, v, t in zip(strikes, iv, t_years)])

    mask = delta_vec <= max_delta

    if not np.any(mask):
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "position_size": position_size,
        })

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
        return _empty_single_result(meta, df, "CC", dvol_index=meta.dvol_index, filters={
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "position_size": position_size,
        })

    c_aprs = [c["apr_notional"] for c in candidates]
    c_upsides = [c["upside_pct"] for c in candidates]
    c_assign = [1.0 - c["assign_prob"] for c in candidates]
    c_liq = [c["liquidity_score"] for c in candidates]

    n_apr = _normalize_score(c_aprs)
    n_upside = _normalize_score(c_upsides)
    n_assign = _normalize_score(c_assign)
    n_liq = _normalize_score(c_liq)

    w_apr, w_upcap, w_assign, w_liq = 0.35, 0.25, 0.20, 0.20

    for i, c in enumerate(candidates):
        score = (w_apr * n_apr[i] + w_upcap * n_upside[i] + w_assign * n_assign[i] + w_liq * n_liq[i]) * 100
        c["score"] = round(score, 1)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:return_count]

    logger.info("CC scan base=%s results=%d top_score=%.1f", df["base"].iloc[0], len(top), top[0]["score"] if top else 0)

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0],
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CC",
        "filters": {
            "max_dte": max_dte, "max_delta": max_delta, "min_oi": min_oi,
            "max_spread_bps": max_spread_bps, "position_size": position_size,
        },
        "candidates": top,
    }
