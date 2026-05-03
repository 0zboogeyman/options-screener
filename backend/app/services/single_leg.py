"""
单腿期权策略扫描器：CSP（现金备兑接货）和 CC（现货备兑抛货）
"""
from __future__ import annotations

import math
from typing import Dict, List
import numpy as np
import pandas as pd

from .quality import compute_mid, spread_flag


def _prep_single_leg_chain(df: pd.DataFrame) -> pd.DataFrame:
    """准备单腿期权数据链"""
    req = [
        "date", "base", "instrument", "expiry_ts", "strike", "option_type",
        "bid", "ask", "mark_price", "mark_iv", "underlying", "oi", "asof_ts",
    ]
    for c in req:
        if c not in df.columns:
            df[c] = np.nan

    # 计算 mid 和 quality
    mids = []
    qflags = []
    spread_ratios = []
    for bid, ask, mark in zip(df["bid"].tolist(), df["ask"].tolist(), df["mark_price"].tolist()):
        bid = None if (bid is None or (isinstance(bid, float) and math.isnan(bid))) else bid
        ask = None if (ask is None or (isinstance(ask, float) and math.isnan(ask))) else ask
        mark = None if (mark is None or (isinstance(mark, float) and math.isnan(mark))) else mark

        mid = compute_mid(bid, ask, mark)
        mids.append(mid)
        qflags.append(spread_flag(bid, ask, mid))

        # 计算点差比例
        if bid and ask and bid > 0 and ask > 0:
            mid_val = (bid + ask) / 2.0
            spread_ratio = (ask - bid) / mid_val if mid_val > 0 else float('inf')
        else:
            spread_ratio = float('inf')
        spread_ratios.append(spread_ratio)

    df = df.copy()
    df["mid"] = mids
    df["quality_flag"] = qflags
    df["spread_ratio"] = spread_ratios
    return df


def _normalize_score(values: List[float]) -> List[float]:
    """归一化得分到 0-1 范围"""
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

    normalized = []
    for v in values:
        if not np.isfinite(v):
            normalized.append(0.0)
        else:
            normalized.append((v - min_val) / (max_val - min_val))

    return normalized


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
    """
    扫描现金备兑接货（CSP）策略

    策略：卖出看跌期权（Put），目标以折扣价格接货或赚取权利金

    Args:
        chain_df: 期权链数据
        meta: 元数据（包含 asof_ts, spot_price等）
        max_dte: 最大到期天数
        max_delta: 最大 Delta 绝对值（用于控制被行权概率）
        min_oi: 最小持仓量
        max_spread_bps: 最大点差（基点）
        available_cash: 可用保证金（USD）
        return_count: 返回结果数量

    Returns:
        包含候选策略的字典
    """
    df = _prep_single_leg_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date
    spot = meta.spot_price

    # 只保留看跌期权
    df = df[df["option_type"].str.upper() == "P"].copy()
    df = df[df["mid"].notna()].copy()

    # 计算 DTE
    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)

    # 筛选条件
    df = df[df["dte"] <= max_dte].copy()
    df = df[df["dte"] > 0].copy()

    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()

    # 过滤点差过大的期权
    df["spread_bps"] = df["spread_ratio"] * 10000
    df = df[df["spread_bps"] <= max_spread_bps].copy()

    if df.empty:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": meta.base if hasattr(meta, 'base') else chain_df["base"].iloc[0] if not chain_df.empty else "",
            "spot_price": spot,
            "strategy": "CSP",
            "candidates": []
        }

    # 计算策略指标
    candidates = []

    for _, row in df.iterrows():
        strike = float(row["strike"])
        mid = float(row["mid"])
        dte = float(row["dte"])
        oi = float(row["oi"]) if not pd.isna(row["oi"]) else 0
        spread_bps = float(row["spread_bps"])

        # 估算 delta（对于 Put，delta 为负）
        # 使用更准确的近似：基于 moneyness 和简化的正态分布
        moneyness = strike / spot

        # OTM Put (strike < spot): delta 接近 0
        # ATM Put (strike ≈ spot): delta 接近 -0.5
        # ITM Put (strike > spot): delta 接近 -1
        if moneyness < 0.9:  # Deep OTM
            estimated_delta = -0.1 * (moneyness / 0.9)
        elif moneyness < 1.0:  # Slightly OTM
            estimated_delta = -0.1 - 0.4 * ((moneyness - 0.9) / 0.1)
        elif moneyness < 1.1:  # Slightly ITM
            estimated_delta = -0.5 - 0.4 * ((moneyness - 1.0) / 0.1)
        else:  # Deep ITM
            estimated_delta = -0.9 - 0.09 * min((moneyness - 1.1), 1.0)

        estimated_delta = max(-0.99, min(-0.01, estimated_delta))
        assign_prob = abs(estimated_delta)

        # 过滤 delta
        if assign_prob > max_delta:
            continue

        # 计算策略指标
        premium = mid * spot  # 权利金（USD）
        breakeven = strike - mid  # 盈亏平衡点
        discount_pct = (spot - breakeven) / spot if spot > 0 else 0  # 折扣百分比

        # 检查保证金是否足够
        # CSP 保证金需求 ≈ strike * 100 (简化)
        required_margin = strike
        if required_margin > available_cash:
            continue

        # APR 计算
        apr = (premium / strike) * (365.0 / dte) if strike > 0 and dte > 0 else 0

        # 流动性得分（基于 OI 和点差）
        liquidity_score = math.log1p(oi) / (1 + spread_bps / 100)

        candidates.append({
            "symbol": row["instrument"],
            "expiry_ts": int(row["expiry_ts"]),
            "expiry_date": pd.Timestamp(row["expiry_ts"], unit='ms').strftime('%Y-%m-%d'),
            "strike": strike,
            "delta": estimated_delta,
            "premium": premium,
            "breakeven": breakeven,
            "discount_pct": discount_pct,
            "apr": apr,
            "assign_prob": assign_prob,
            "oi": oi,
            "spread_bps": spread_bps,
            "dte": dte,
            "liquidity_score": liquidity_score,
            "quality": row["quality_flag"],
        })

    if not candidates:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": df["base"].iloc[0] if not df.empty else "",
            "spot_price": spot,
            "strategy": "CSP",
            "candidates": []
        }

    # 计算综合得分
    aprs = [c["apr"] for c in candidates]
    discounts = [c["discount_pct"] for c in candidates]
    assign_probs = [c["assign_prob"] for c in candidates]
    liq_scores = [c["liquidity_score"] for c in candidates]

    norm_apr = _normalize_score(aprs)
    norm_discount = _normalize_score(discounts)
    norm_assign = _normalize_score([1.0 - p for p in assign_probs])  # 反转：低行权概率得高分
    norm_liq = _normalize_score(liq_scores)

    # 权重配置
    w_apr = 0.35
    w_buffer = 0.25
    w_assign = 0.20
    w_liq = 0.20

    for i, c in enumerate(candidates):
        score = (
            w_apr * norm_apr[i] +
            w_buffer * norm_discount[i] +
            w_assign * norm_assign[i] +
            w_liq * norm_liq[i]
        ) * 100  # 转换为 0-100 分
        c["score"] = round(score, 1)

    # 按得分排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:return_count]

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0] if not df.empty else "",
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CSP",
        "filters": {
            "max_dte": max_dte,
            "max_delta": max_delta,
            "min_oi": min_oi,
            "max_spread_bps": max_spread_bps,
            "available_cash": available_cash,
        },
        "candidates": top_candidates
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
    """
    扫描现货备兑抛货（CC）策略

    策略：在持有现货的基础上，卖出看涨期权（Call）获取额外收益

    Args:
        chain_df: 期权链数据
        meta: 元数据
        max_dte: 最大到期天数
        max_delta: 最大 Delta 绝对值
        min_oi: 最小持仓量
        max_spread_bps: 最大点差（基点）
        position_size: 持仓合约数量（张）
        return_count: 返回结果数量

    Returns:
        包含候选策略的字典
    """
    df = _prep_single_leg_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date
    spot = meta.spot_price

    # 只保留看涨期权
    df = df[df["option_type"].str.upper() == "C"].copy()
    df = df[df["mid"].notna()].copy()

    # 计算 DTE
    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)

    # 筛选条件
    df = df[df["dte"] <= max_dte].copy()
    df = df[df["dte"] > 0].copy()

    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()

    # 过滤点差过大的期权
    df["spread_bps"] = df["spread_ratio"] * 10000
    df = df[df["spread_bps"] <= max_spread_bps].copy()

    if df.empty:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": meta.base if hasattr(meta, 'base') else chain_df["base"].iloc[0] if not chain_df.empty else "",
            "spot_price": spot,
            "strategy": "CC",
            "candidates": []
        }

    # 计算策略指标
    candidates = []

    for _, row in df.iterrows():
        strike = float(row["strike"])
        mid = float(row["mid"])
        dte = float(row["dte"])
        oi = float(row["oi"]) if not pd.isna(row["oi"]) else 0
        spread_bps = float(row["spread_bps"])

        # 估算 delta（对于 Call，delta 为正）
        # 使用更准确的近似：基于 moneyness 和简化的正态分布
        moneyness = strike / spot

        # OTM Call (strike > spot): delta 接近 0
        # ATM Call (strike ≈ spot): delta 接近 0.5
        # ITM Call (strike < spot): delta 接近 1
        if moneyness > 1.1:  # Deep OTM
            estimated_delta = 0.1 * (1.1 / moneyness)
        elif moneyness > 1.0:  # Slightly OTM
            estimated_delta = 0.1 + 0.4 * ((1.1 - moneyness) / 0.1)
        elif moneyness > 0.9:  # Slightly ITM
            estimated_delta = 0.5 + 0.4 * ((1.0 - moneyness) / 0.1)
        else:  # Deep ITM
            estimated_delta = 0.9 + 0.09 * min((0.9 - moneyness) / 0.1, 1.0)

        estimated_delta = max(0.01, min(0.99, estimated_delta))
        assign_prob = estimated_delta

        # 过滤 delta
        if assign_prob > max_delta:
            continue

        # 计算策略指标
        premium = mid * spot * position_size  # 权利金（USD）
        upside_pct = (strike - spot) / spot if spot > 0 else 0  # 上涨空间

        # APR (基于名义本金)
        notional = spot * position_size
        apr_notional = (premium / notional) * (365.0 / dte) if notional > 0 and dte > 0 else 0

        # 流动性得分
        liquidity_score = math.log1p(oi) / (1 + spread_bps / 100)

        candidates.append({
            "symbol": row["instrument"],
            "expiry_ts": int(row["expiry_ts"]),
            "expiry_date": pd.Timestamp(row["expiry_ts"], unit='ms').strftime('%Y-%m-%d'),
            "strike": strike,
            "delta": estimated_delta,
            "premium": premium,
            "upside_pct": upside_pct,
            "apr_notional": apr_notional,
            "assign_prob": assign_prob,
            "oi": oi,
            "spread_bps": spread_bps,
            "dte": dte,
            "liquidity_score": liquidity_score,
            "quality": row["quality_flag"],
        })

    if not candidates:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": df["base"].iloc[0] if not df.empty else "",
            "spot_price": spot,
            "strategy": "CC",
            "candidates": []
        }

    # 计算综合得分
    aprs = [c["apr_notional"] for c in candidates]
    upsides = [c["upside_pct"] for c in candidates]
    assign_probs = [c["assign_prob"] for c in candidates]
    liq_scores = [c["liquidity_score"] for c in candidates]

    norm_apr = _normalize_score(aprs)
    norm_upside = _normalize_score(upsides)
    norm_assign = _normalize_score([1.0 - p for p in assign_probs])  # 反转：低行权概率得高分
    norm_liq = _normalize_score(liq_scores)

    # 权重配置
    w_apr = 0.35
    w_upcap = 0.25
    w_assign = 0.20
    w_liq = 0.20

    for i, c in enumerate(candidates):
        score = (
            w_apr * norm_apr[i] +
            w_upcap * norm_upside[i] +
            w_assign * norm_assign[i] +
            w_liq * norm_liq[i]
        ) * 100
        c["score"] = round(score, 1)

    # 按得分排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:return_count]

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": df["base"].iloc[0] if not df.empty else "",
        "spot_price": spot,
        "dvol_index": meta.dvol_index,
        "strategy": "CC",
        "filters": {
            "max_dte": max_dte,
            "max_delta": max_delta,
            "min_oi": min_oi,
            "max_spread_bps": max_spread_bps,
            "position_size": position_size,
        },
        "candidates": top_candidates
    }
