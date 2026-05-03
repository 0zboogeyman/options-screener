from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import math
import numpy as np
import pandas as pd

from .bs import pop_for_vertical
from .quality import compute_mid, spread_flag


TENOR_NEAR = (7, 21)
TENOR_MID = (22, 60)
TENOR_FAR = (61, 180)

# Opinion 模式的时间范围定义（天数）
HORIZON_SHORT = (7, 30)      # ≤1个月
HORIZON_MID = (31, 90)       # 1-3个月
HORIZON_LONG = (91, 365)     # ≥3个月


def _tenor_window(tenor: str) -> Tuple[int, int]:
    tenor = tenor.lower()
    if tenor == "near":
        return TENOR_NEAR
    if tenor == "mid":
        return TENOR_MID
    return TENOR_FAR


def _horizon_window(horizon: str) -> Tuple[int, int]:
    """Opinion 模式的时间范围"""
    horizon = horizon.lower()
    if horizon == "short":
        return HORIZON_SHORT
    if horizon == "mid":
        return HORIZON_MID
    return HORIZON_LONG


def _compute_spread_ratio(bid, ask):
    """计算 spread_ratio = (ask - bid) / ((ask + bid) / 2)

    如果 bid<=0 或 ask<=0 或计算无效，返回 +inf（表示应过滤）
    """
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return float('inf')
    mid_price = (bid + ask) / 2.0
    if mid_price <= 0:
        return float('inf')
    return (ask - bid) / mid_price


def _prep_chain(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure minimal columns are present and compute mid/quality
    req = [
        "date",
        "base",
        "instrument",
        "expiry_ts",
        "strike",
        "option_type",
        "bid",
        "ask",
        "mark_price",
        "mark_iv",
        "underlying",
        "oi",
        "asof_ts",
    ]
    for c in req:
        if c not in df.columns:
            df[c] = np.nan

    mids = []
    qflags = []
    spread_ratios = []
    for bid, ask, mark in zip(df["bid"].tolist(), df["ask"].tolist(), df["mark_price"].tolist()):
        mid = compute_mid(_nan_to_none(bid), _nan_to_none(ask), _nan_to_none(mark))
        mids.append(mid)
        qflags.append(spread_flag(_nan_to_none(bid), _nan_to_none(ask), _nan_to_none(mid)))
        spread_ratios.append(_compute_spread_ratio(_nan_to_none(bid), _nan_to_none(ask)))

    df = df.copy()
    df["mid"] = mids
    df["quality_flag"] = qflags
    df["spread_ratio"] = spread_ratios
    return df


def _nan_to_none(x):
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x


def _within_tenor(dte: float, tw: Tuple[int, int]) -> bool:
    return tw[0] <= dte <= tw[1]


def _calc_vertical_metrics(kind: str, side: str, k1: float, k2: float, long_px: float, short_px: float,
                           s: float, iv: float, t_years: float) -> Dict:
    # Premium: debit: long - short; credit: short - long (币本位)
    strike_width = abs(k2 - k1)  # 金本位差价 (USD)

    if side == "DEBIT":
        premium = (long_px - short_px)  # 币本位
        # 借方价差：最大收益 = 行权价差价（金本位USD），最大亏损 = 权利金付出（币本位）
        max_profit = strike_width  # 金本位
        max_loss = premium  # 币本位
    else:
        premium = (short_px - long_px)  # 币本位
        # 贷方价差：最大收益 = 权利金收入（币本位），最大亏损 = 行权价差价（金本位USD）
        max_profit = premium  # 币本位
        max_loss = strike_width  # 金本位

    # 赔率 = 行权价差价(USD) / 权利金的金本位数值(USD)
    premium_usd = premium * s
    if premium_usd <= 0:
        odds = float("inf") if strike_width > 0 else float("nan")
    else:
        odds = strike_width / premium_usd

    pop = pop_for_vertical(kind=kind, side=side, s=s, k1=k1, k2=k2, premium=premium, vol=max(iv, 1e-6), t_years=max(t_years, 1e-6))

    return {
        "premium": float(premium),
        "max_profit": float(max_profit),
        "max_loss": float(max_loss),
        "odds": float(odds),
        "pop": None if (isinstance(pop, float) and (math.isnan(pop) or pop < 0 or pop > 1)) else float(pop),
    }


def scan_buckets(
    chain_df: pd.DataFrame,
    meta,
    tenor: str,
    direction: str,
    return_per_bucket: int = 3,
    min_oi: int = 0,
    max_width: float | None = None,
):
    df = _prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date

    df = df[df["mid"].notna()].copy()

    # 过滤 spread_ratio > 0.5 的期权（买卖价差过宽，流动性差）
    df = df[df["spread_ratio"] <= 0.5].copy()

    if min_oi:
        df = df[df["oi"].fillna(0) >= min_oi]

    # dte days
    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    tmin, tmax = _tenor_window(tenor)
    df = df[(df["dte"] >= tmin) & (df["dte"] <= tmax)].copy()
    if df.empty:
        return {"asof_date": date, "base": df["base"].iloc[0] if not df.empty else "", "tenor": tenor, "buckets": []}

    out_buckets = []
    for kind in ["CALL", "PUT"]:
        sub = df[df["option_type"].str.upper() == ("C" if kind == "CALL" else "P")].copy()
        if sub.empty:
            continue
        # group by expiry
        for exp_ts, grp in sub.groupby("expiry_ts"):
            grp = grp.sort_values("strike")
            strikes = grp["strike"].values
            mids = grp["mid"].values
            ivs = grp["mark_iv"].values
            s_vals = grp["underlying"].values
            s = float(np.nanmean(s_vals)) if len(s_vals) else float("nan")
            iv = float(np.nanmean(ivs)) if len(ivs) else float("nan")
            t_years = max(((exp_ts - asof) / (1000 * 60 * 60 * 24)) / 365.0, 1e-6)

            legs_debit = []
            legs_credit = []
            n = len(strikes)
            for i in range(n):
                for j in range(i + 1, n):
                    k1 = float(strikes[i])
                    k2 = float(strikes[j])
                    if max_width is not None and (k2 - k1) > max_width:
                        continue

                    # 过滤实值期权（ITM）
                    # 看涨期权：过滤掉 K < 现货价格
                    # 看跌期权：过滤掉 K > 现货价格
                    if kind == "CALL":
                        # 看涨价差：两个执行价都应该是虚值或平值（K >= S）
                        if k1 < s or k2 < s:
                            continue
                    else:  # PUT
                        # 看跌价差：两个执行价都应该是虚值或平值（K <= S）
                        if k1 > s or k2 > s:
                            continue

                    # For calls: debit long k1, short k2; credit short k1, long k2
                    # For puts (put debit defined as buy K2 sell K1 in doc), we keep same K ordering (k1<k2)
                    m1 = float(mids[i])
                    m2 = float(mids[j])

                    # Quality: if either flag wide/missing/invalid mark it
                    q1 = grp.iloc[i]["quality_flag"]
                    q2 = grp.iloc[j]["quality_flag"]
                    qflag = "ok"
                    for q in (q1, q2):
                        if q in ("missing", "invalid", "wide_spread"):
                            qflag = q
                            break

                    if kind == "CALL":
                        debit = _calc_vertical_metrics("CALL", "DEBIT", k1, k2, long_px=m1, short_px=m2, s=s, iv=iv, t_years=t_years)
                        credit = _calc_vertical_metrics("CALL", "CREDIT", k1, k2, long_px=m2, short_px=m1, s=s, iv=iv, t_years=t_years)
                    else:
                        # Puts: for debit in doc: Buy Put(K2) (higher), Sell Put(K1) (lower)
                        # With k1<k2, debit long m2 short m1; credit short m2 long m1
                        debit = _calc_vertical_metrics("PUT", "DEBIT", k1, k2, long_px=m2, short_px=m1, s=s, iv=iv, t_years=t_years)
                        credit = _calc_vertical_metrics("PUT", "CREDIT", k1, k2, long_px=m1, short_px=m2, s=s, iv=iv, t_years=t_years)

                    # 过滤掉权利金过小的组合（金本位USD < 10）
                    # 避免深度虚值期权导致的极端赔率
                    premium_usd_debit = abs(debit["premium"]) * s
                    premium_usd_credit = abs(credit["premium"]) * s

                    if premium_usd_debit >= 10:
                        legs_debit.append({"K1": k1, "K2": k2, **debit, "quality": qflag})
                    if premium_usd_credit >= 10:
                        legs_credit.append({"K1": k1, "K2": k2, **credit, "quality": qflag})

            # Rank by odds
            def _rank(lst: List[Dict]):
                lst = [x for x in lst if not math.isnan(x["odds"]) and x["odds"] != float("inf")]
                lst.sort(key=lambda x: x["odds"], reverse=True)
                top = lst[:return_per_bucket]
                bottom = lst[-return_per_bucket:][::-1] if return_per_bucket > 0 else []
                return top, bottom

            top_d, bot_d = _rank(legs_debit)
            top_c, bot_c = _rank(legs_credit)

            out_buckets.append({"leg_type": kind, "side": "DEBIT", "top": top_d, "bottom": bot_d})
            out_buckets.append({"leg_type": kind, "side": "CREDIT", "top": top_c, "bottom": bot_c})

    # Optionally filter by direction: up → CALL focus; down → PUT focus (but keep both for completeness)
    if direction == "up":
        filtered = [b for b in out_buckets if b["leg_type"] == "CALL"]
    elif direction == "down":
        filtered = [b for b in out_buckets if b["leg_type"] == "PUT"]
    else:
        filtered = out_buckets

    base = chain_df["base"].iloc[0] if not chain_df.empty else ""

    # Get spot price: 优先使用 manifest 中的标准指数价格，否则回退到期权数据的平均值
    spot_price = meta.spot_price
    if spot_price is None and not chain_df.empty and "underlying" in chain_df.columns:
        underlying_vals = chain_df["underlying"].dropna()
        if len(underlying_vals) > 0:
            spot_price = float(underlying_vals.median())  # 使用中位数更稳健

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": base,
        "spot_price": spot_price,
        "dvol_index": meta.dvol_index,
        "tenor": tenor,
        "buckets": filtered
    }


def _snap_to_grid(target: float, strikes: np.ndarray) -> Tuple[float, int, bool]:
    """
    将目标价对齐到最近的可交易行权价
    返回：(对齐后的行权价, 索引, 是否发生了对齐)
    """
    if len(strikes) == 0:
        return target, -1, False

    idx = None
    min_diff = float('inf')
    for i, k in enumerate(strikes):
        diff = abs(k - target)
        if diff < min_diff:
            min_diff = diff
            idx = i

    snapped_strike = float(strikes[idx])
    was_snapped = abs(snapped_strike - target) > 0.01
    return snapped_strike, idx, was_snapped


def scan_opinion_spreads(
    chain_df: pd.DataFrame,
    meta,
    horizon: str,
    view: str,
    target_price: float,
    max_gap_steps: int = 8,
    return_count: int = 3,
):
    """
    根据用户观点筛选价差策略：
    - up: 会上涨到 ≥ P → Call 借方价差（固定 K2=P，枚举 K1<K2）
    - down: 会下跌到 ≤ P → Put 借方价差（固定 K1=P，枚举 K2<K1）
    - not_up: 不会上涨到 ≥ P → Call 贷方价差（固定 K2=P，枚举 K1<K2）
    - not_down: 不会下跌到 ≤ P → Put 贷方价差（固定 K1=P，枚举 K2<K1）
    跨到期聚合，返回赔率最高/最低的 Top N 策略
    """
    df = _prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date

    df = df[df["mid"].notna()].copy()

    # 过滤 spread_ratio > 0.5
    df = df[df["spread_ratio"] <= 0.5].copy()

    # 计算 DTE
    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    tmin, tmax = _horizon_window(horizon)
    df = df[(df["dte"] >= tmin) & (df["dte"] <= tmax)].copy()

    # 确定期权类型和价差类型
    if view == "up":
        kind = "CALL"
        side = "DEBIT"
        anchor_leg = "K2"
    elif view == "not_up":
        kind = "CALL"
        side = "CREDIT"
        anchor_leg = "K1"  # 固定 K1=P，卖出 K1 Call
    elif view == "down":
        kind = "PUT"
        side = "DEBIT"
        anchor_leg = "K1"
    else:  # not_down
        kind = "PUT"
        side = "CREDIT"
        anchor_leg = "K1"  # 固定 K1=P，卖出 K1 Put

    if df.empty:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": meta.base if hasattr(meta, 'base') else chain_df["base"].iloc[0] if not chain_df.empty else "",
            "spot_price": meta.spot_price,
            "dvol_index": meta.dvol_index,
            "horizon": horizon,
            "view": view,
            "anchor_leg": anchor_leg,
            "anchor_strike": target_price,
            "items": [],
            "notes": {"strike_snapped": False, "original_target": target_price}
        }

    # 根据 view 选择期权类型
    df = df[df["option_type"].str.upper() == ("C" if kind == "CALL" else "P")].copy()

    if df.empty:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": chain_df["base"].iloc[0] if not chain_df.empty else "",
            "spot_price": meta.spot_price,
            "dvol_index": meta.dvol_index,
            "horizon": horizon,
            "view": view,
            "anchor_leg": anchor_leg,
            "anchor_strike": target_price,
            "items": [],
            "notes": {"strike_snapped": False, "original_target": target_price}
        }

    candidates = []
    strike_snapped = False

    # 收集所有到期日的行权价并集，用于snap目标价
    all_strikes = sorted(df["strike"].unique())
    if len(all_strikes) == 0:
        return {
            "asof_date": date,
            "asof_ts": asof,
            "base": chain_df["base"].iloc[0] if not chain_df.empty else "",
            "spot_price": meta.spot_price,
            "dvol_index": meta.dvol_index,
            "horizon": horizon,
            "view": view,
            "anchor_leg": anchor_leg,
            "anchor_strike": target_price,
            "items": [],
            "notes": {"strike_snapped": False, "original_target": target_price}
        }

    unified_anchor_strike, _, was_snapped = _snap_to_grid(target_price, np.array(all_strikes))
    if was_snapped:
        strike_snapped = True

    # 按到期日分组处理
    for exp_ts, grp in df.groupby("expiry_ts"):
        grp = grp.sort_values("strike")
        strikes = grp["strike"].values
        mids = grp["mid"].values
        ivs = grp["mark_iv"].values
        s_vals = grp["underlying"].values

        s = float(np.nanmean(s_vals)) if len(s_vals) else float("nan")
        iv = float(np.nanmean(ivs)) if len(ivs) else float("nan")
        t_years = max(((exp_ts - asof) / (1000 * 60 * 60 * 24)) / 365.0, 1e-6)

        # 检查这个到期日是否有统一的anchor_strike
        anchor_idx = np.where(strikes == unified_anchor_strike)[0]
        if len(anchor_idx) == 0:
            # 这个到期日没有目标行权价，跳过
            continue

        anchor_idx = int(anchor_idx[0])
        anchor_strike = unified_anchor_strike
        anchor_mid = float(mids[anchor_idx])

        # 根据 view 确定锚定腿和候选腿
        if view == "up":
            # 会上涨到 ≥ P：Call 借方价差，固定 K2=P，枚举 K1<K2
            k2, k2_idx, m2 = anchor_strike, anchor_idx, anchor_mid
            if k2 < s:
                continue
            k1_candidates = [(i, k, m) for i, (k, m) in enumerate(zip(strikes, mids))
                           if k < k2 and i >= anchor_idx - max_gap_steps]

            for k1_idx, k1, m1 in k1_candidates:
                q1, q2 = grp.iloc[k1_idx]["quality_flag"], grp.iloc[k2_idx]["quality_flag"]
                if q1 in ("missing", "invalid") or q2 in ("missing", "invalid"):
                    continue

                metrics = _calc_vertical_metrics("CALL", "DEBIT", k1, k2, long_px=m1, short_px=m2, s=s, iv=iv, t_years=t_years)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < 10 or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue

                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit='ms').strftime('%Y-%m-%d'),
                    "K1": float(k1), "K2": float(k2),
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        elif view == "down":
            # 会下跌到 ≤ P：Put 借方价差，固定 K1=P，枚举 K2<K1
            k1, k1_idx, m1 = anchor_strike, anchor_idx, anchor_mid
            if k1 > s:
                continue
            k2_candidates = [(i, k, m) for i, (k, m) in enumerate(zip(strikes, mids))
                           if k < k1 and i >= anchor_idx - max_gap_steps]

            for k2_idx, k2, m2 in k2_candidates:
                q1, q2 = grp.iloc[k1_idx]["quality_flag"], grp.iloc[k2_idx]["quality_flag"]
                if q1 in ("missing", "invalid") or q2 in ("missing", "invalid"):
                    continue

                metrics = _calc_vertical_metrics("PUT", "DEBIT", k1, k2, long_px=m1, short_px=m2, s=s, iv=iv, t_years=t_years)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < 10 or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue

                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit='ms').strftime('%Y-%m-%d'),
                    "K1": float(k1), "K2": float(k2),
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        elif view == "not_up":
            # 不会上涨到 ≥ P：Call 贷方价差，固定 K1=P，枚举 K2>K1
            k1, k1_idx, m1 = anchor_strike, anchor_idx, anchor_mid

            # 过滤实值期权：Call 的 K1 和 K2 都应该 >= 现货价（虚值或平值）
            if k1 < s:
                continue

            k2_candidates = [(i, k, m) for i, (k, m) in enumerate(zip(strikes, mids))
                           if k > k1 and i <= anchor_idx + max_gap_steps]

            for k2_idx, k2, m2 in k2_candidates:
                # K2 也必须是虚值或平值
                if k2 < s:
                    continue

                q1, q2 = grp.iloc[k1_idx]["quality_flag"], grp.iloc[k2_idx]["quality_flag"]
                if q1 in ("missing", "invalid") or q2 in ("missing", "invalid"):
                    continue

                # Call 贷方价差：卖出 K1（低），买入 K2（高）作为保护
                metrics = _calc_vertical_metrics("CALL", "CREDIT", k1, k2, long_px=m2, short_px=m1, s=s, iv=iv, t_years=t_years)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < 10 or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue

                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit='ms').strftime('%Y-%m-%d'),
                    "K1": float(k1), "K2": float(k2),
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        else:  # not_down
            # 不会下跌到 ≤ P：Put 贷方价差，固定 K1=P，枚举 K2<K1
            k1, k1_idx, m1 = anchor_strike, anchor_idx, anchor_mid

            # 过滤实值期权：Put 的 K1 和 K2 都应该 <= 现货价（虚值或平值）
            if k1 > s:
                continue

            k2_candidates = [(i, k, m) for i, (k, m) in enumerate(zip(strikes, mids))
                           if k < k1 and i >= anchor_idx - max_gap_steps]

            for k2_idx, k2, m2 in k2_candidates:
                # K2 也必须是虚值或平值
                if k2 > s:
                    continue

                q1, q2 = grp.iloc[k1_idx]["quality_flag"], grp.iloc[k2_idx]["quality_flag"]
                if q1 in ("missing", "invalid") or q2 in ("missing", "invalid"):
                    continue

                # Put 贷方价差：卖出 K1（高），买入 K2（低）作为保护
                metrics = _calc_vertical_metrics("PUT", "CREDIT", k1, k2, long_px=m2, short_px=m1, s=s, iv=iv, t_years=t_years)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < 10 or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue

                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit='ms').strftime('%Y-%m-%d'),
                    "K1": float(k1), "K2": float(k2),
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

    # 贷方策略按赔率升序（低赔率=高胜率），借方策略按赔率降序（高赔率）
    if side == "CREDIT":
        candidates.sort(key=lambda x: (x["odds"], x["premium"]))
    else:
        candidates.sort(key=lambda x: (-x["odds"], -x["max_profit"], x["premium"]))

    top_strategies = candidates[:return_count]

    base = chain_df["base"].iloc[0] if not chain_df.empty else ""
    spot_price = meta.spot_price
    if spot_price is None and not chain_df.empty and "underlying" in chain_df.columns:
        underlying_vals = chain_df["underlying"].dropna()
        if len(underlying_vals) > 0:
            spot_price = float(underlying_vals.median())

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": base,
        "spot_price": spot_price,
        "dvol_index": meta.dvol_index,
        "horizon": horizon,
        "view": view,
        "side": side,
        "anchor_leg": anchor_leg,
        "anchor_strike": unified_anchor_strike,
        "items": top_strategies,
        "notes": {
            "strike_snapped": strike_snapped,
            "original_target": target_price
        }
    }

