from __future__ import annotations

import heapq
import logging
from typing import Dict, List, Tuple

import math
import numpy as np
import pandas as pd

from .bs import pop_for_vertical
from .preprocessing import prep_chain
from .svi import svi_iv

logger = logging.getLogger(__name__)


TENOR_NEAR = (7, 21)
TENOR_MID = (22, 60)
TENOR_FAR = (61, 180)

HORIZON_SHORT = (7, 30)
HORIZON_MID = (31, 90)
HORIZON_LONG = (91, 365)

# 单腿买卖价差（相对中间价）超过该值视为不可用腿，扫描时剔除。
# 与 preprocessing.WIDE_SPREAD_THRESHOLD=0.15 的"打标"语义区分：这里是过滤阈值。
# 0.35 阈值基于 Deribit 真实市场数据（BTC+ETH 1412 样本）系统性评估：
#   F1=0.775（接近峰值 0.776）、Recall=0.987、avg_odds 比 0.5 低约 30%，候选质量更纯。
SPREAD_RATIO_MAX = 0.35
# 组合权利金（美元）低于该值不进入候选（避免深度虚值腿干扰排序）
MIN_PREMIUM_USD = 10.0
# scan_buckets 组合扫描时，两腿之间允许的最大行权价步数；
# 将 O(n²) 组合降为 O(n·g)，宽跨度组合的赔率通常极差，对 top 结果影响可忽略
DEFAULT_MAX_GAP_STEPS = 10


def _tenor_window(tenor: str) -> Tuple[int, int]:
    tenor = tenor.lower()
    if tenor == "near":
        return TENOR_NEAR
    if tenor == "mid":
        return TENOR_MID
    return TENOR_FAR


def _horizon_window(horizon: str) -> Tuple[int, int]:
    horizon = horizon.lower()
    if horizon == "short":
        return HORIZON_SHORT
    if horizon == "mid":
        return HORIZON_MID
    return HORIZON_LONG


def _empty_scan_result(meta, df: pd.DataFrame, **extra) -> Dict:
    base = df["base"].iloc[0] if not df.empty else ""
    return {
        "asof_date": meta.date,
        "asof_ts": int(meta.asof_ts),
        "base": base,
        "spot_price": meta.spot_price,
        "dvol_index": meta.dvol_index,
        **extra,
    }


def _calc_vertical_metrics(kind: str, side: str, k1: float, k2: float, long_px: float, short_px: float,
                           s: float, iv: float, t_years: float, iv_at=None) -> Dict:
    """计算垂直价差指标。

    iv_at：可选回调 iv_at(k_be) -> iv，按盈亏平衡行权价取 SVI 逐行权价 IV；
    为 None 时用传入的 iv（兼容旧调用）。
    注意 PoP 的 premium 必须换算成 USD（k 是 USD、premium 是币种），
    旧版直接把币种 premium 加在 USD 行权价上属于单位混用。
    """
    strike_width = abs(k2 - k1)

    if side == "DEBIT":
        premium = (long_px - short_px)
        max_profit = strike_width
        max_loss = premium
    else:
        premium = (short_px - long_px)
        max_profit = premium
        max_loss = strike_width

    premium_usd = premium * s
    if premium_usd <= 0:
        odds = float("inf") if strike_width > 0 else float("nan")
    else:
        odds = strike_width / premium_usd

    if iv_at is not None and math.isfinite(premium_usd):
        k_be = (k1 + premium_usd) if kind.upper() == "CALL" else (k2 - premium_usd)
        vol_be = float(iv_at(k_be))
        if not math.isfinite(vol_be) or vol_be <= 0:
            vol_be = iv
    else:
        vol_be = iv
    pop = pop_for_vertical(kind=kind, side=side, s=s, k1=k1, k2=k2, premium=premium_usd,
                           vol=max(vol_be, 1e-6), t_years=max(t_years, 1e-6))

    return {
        "premium": float(premium),
        "max_profit": float(max_profit),
        "max_loss": float(max_loss),
        "odds": float(odds),
        "pop": None if (isinstance(pop, float) and (math.isnan(pop) or pop < 0 or pop > 1)) else float(pop),
    }


def _buy_sell_arrays(grp: pd.DataFrame, mids: np.ndarray, pricing_mode: str):
    """按 pricing_mode 生成买入/卖出价数组（conservative：买 ask 卖 bid，缺边回退 mid）。"""
    if pricing_mode != "conservative":
        return mids, mids
    bid = pd.to_numeric(grp["bid"], errors="coerce").to_numpy(dtype=float)
    ask = pd.to_numeric(grp["ask"], errors="coerce").to_numpy(dtype=float)
    buy = np.where(np.isfinite(ask) & (ask > 0), ask, mids)
    sell = np.where(np.isfinite(bid) & (bid > 0), bid, mids)
    return buy, sell


def scan_buckets(
    chain_df: pd.DataFrame,
    meta,
    tenor: str,
    direction: str,
    return_per_bucket: int = 3,
    min_oi: int = 0,
    max_width: float | None = None,
    max_gap_steps: int = DEFAULT_MAX_GAP_STEPS,
    svi_surface: Dict[int, Dict] | None = None,
    pricing_mode: str = "mid",
):
    df = prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date

    df = df[df["mid"].notna()].copy()
    df = df[df["spread_ratio"] <= SPREAD_RATIO_MAX].copy()

    if min_oi:
        df = df[df["oi"].fillna(0) >= min_oi]

    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    tmin, tmax = _tenor_window(tenor)
    df = df[(df["dte"] >= tmin) & (df["dte"] <= tmax)].copy()
    if df.empty:
        return {**_empty_scan_result(meta, df, tenor=tenor), "buckets": []}

    out_buckets = []
    for kind in ["CALL", "PUT"]:
        sub = df[df["option_type"].str.upper() == ("C" if kind == "CALL" else "P")].copy()
        if sub.empty:
            continue
        for exp_ts, grp in sub.groupby("expiry_ts"):
            grp = grp.sort_values("strike")
            strikes = grp["strike"].values
            mids = grp["mid"].values
            ivs = grp["mark_iv"].values
            s_vals = grp["underlying"].values
            qflags = grp["quality_flag"].values
            spread_ratios = grp["spread_ratio"].values
            s = float(np.nanmean(s_vals)) if len(s_vals) else float("nan")
            iv = float(np.nanmean(ivs)) if len(ivs) else float("nan")
            t_years = max(((exp_ts - asof) / (1000 * 60 * 60 * 24)) / 365.0, 1e-6)

            # SVI 逐行权价 IV（PoP 用）；无 ok 切片时回退到期均值 IV
            iv_at = None
            params = (svi_surface or {}).get(int(exp_ts))
            if params is not None:
                k_grid = np.log(strikes / max(s, 1e-9))
                iv_grid = svi_iv(k_grid, params, t_years)
                iv_at = lambda kb, _sg=strikes, _ig=iv_grid: float(np.interp(kb, _sg, _ig))

            buy_arr, sell_arr = _buy_sell_arrays(grp, mids, pricing_mode)

            n = len(strikes)
            valid_mask = np.ones(n, dtype=bool)
            for i in range(n):
                if qflags[i] in ("missing", "invalid", "wide_spread"):
                    valid_mask[i] = False

            valid_indices = np.where(valid_mask)[0]
            if len(valid_indices) < 2:
                continue

            legs_debit = []
            legs_credit = []

            vi = valid_indices
            for a in range(len(vi)):
                i = vi[a]
                k1 = float(strikes[i])
                if kind == "CALL" and k1 < s:
                    continue
                if kind == "PUT" and k1 > s:
                    continue

                for b in range(a + 1, min(len(vi), a + 1 + max_gap_steps)):
                    j = vi[b]
                    k2 = float(strikes[j])
                    if max_width is not None and (k2 - k1) > max_width:
                        continue
                    if kind == "CALL" and k2 < s:
                        continue
                    if kind == "PUT" and k2 > s:
                        continue

                    # 买腿取 buy 价、卖腿取 sell 价（conservative 时为可执行价）
                    if kind == "CALL":
                        debit = _calc_vertical_metrics("CALL", "DEBIT", k1, k2, long_px=buy_arr[i], short_px=sell_arr[j], s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                        credit = _calc_vertical_metrics("CALL", "CREDIT", k1, k2, long_px=buy_arr[j], short_px=sell_arr[i], s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                    else:
                        debit = _calc_vertical_metrics("PUT", "DEBIT", k1, k2, long_px=buy_arr[j], short_px=sell_arr[i], s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                        credit = _calc_vertical_metrics("PUT", "CREDIT", k1, k2, long_px=buy_arr[i], short_px=sell_arr[j], s=s, iv=iv, t_years=t_years, iv_at=iv_at)

                    premium_usd_debit = abs(debit["premium"]) * s
                    premium_usd_credit = abs(credit["premium"]) * s
                    spread_avg = float((spread_ratios[i] + spread_ratios[j]) / 2.0)

                    if premium_usd_debit >= MIN_PREMIUM_USD:
                        legs_debit.append({"K1": k1, "K2": k2, **debit, "quality": "ok", "spread_ratio_avg": spread_avg})
                    if premium_usd_credit >= MIN_PREMIUM_USD:
                        legs_credit.append({"K1": k1, "K2": k2, **credit, "quality": "ok", "spread_ratio_avg": spread_avg})

            def _rank(lst: List[Dict]):
                lst = [x for x in lst if not math.isnan(x["odds"]) and x["odds"] != float("inf")]
                # 流动性惩罚：两腿平均点差越接近过滤上限，调整赔率越低（最多 -50%）
                for x in lst:
                    sr = x.get("spread_ratio_avg")
                    penalty = 0.5 * min(sr / SPREAD_RATIO_MAX, 1.0) if sr is not None and math.isfinite(sr) else 0.0
                    x["odds_adj"] = x["odds"] * (1.0 - penalty)
                top = heapq.nlargest(return_per_bucket, lst, key=lambda x: x["odds_adj"])
                bottom = heapq.nsmallest(return_per_bucket, lst, key=lambda x: x["odds_adj"])
                return top, bottom

            top_d, bot_d = _rank(legs_debit)
            top_c, bot_c = _rank(legs_credit)

            out_buckets.append({"leg_type": kind, "side": "DEBIT", "top": top_d, "bottom": bot_d})
            out_buckets.append({"leg_type": kind, "side": "CREDIT", "top": top_c, "bottom": bot_c})

    if direction == "up":
        filtered = [b for b in out_buckets if b["leg_type"] == "CALL"]
    elif direction == "down":
        filtered = [b for b in out_buckets if b["leg_type"] == "PUT"]
    else:
        filtered = out_buckets

    base = chain_df["base"].iloc[0] if not chain_df.empty else ""

    spot_price = meta.spot_price
    if spot_price is None and not chain_df.empty and "underlying" in chain_df.columns:
        underlying_vals = chain_df["underlying"].dropna()
        if len(underlying_vals) > 0:
            spot_price = float(underlying_vals.median())

    logger.info("Scanned spread buckets base=%s tenor=%s direction=%s results=%d", base, tenor, direction, len(filtered))

    return {
        "asof_date": date,
        "asof_ts": asof,
        "base": base,
        "spot_price": spot_price,
        "dvol_index": meta.dvol_index,
        "tenor": tenor,
        "pricing_mode": pricing_mode,
        "buckets": filtered,
    }


def _snap_to_grid(target: float, strikes: np.ndarray) -> Tuple[float, int, bool]:
    if len(strikes) == 0:
        return target, -1, False

    idx = np.argmin(np.abs(strikes - target))
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
    svi_surface: Dict[int, Dict] | None = None,
    pricing_mode: str = "mid",
):
    df = prep_chain(chain_df)
    asof = int(meta.asof_ts)
    date = meta.date

    df = df[df["mid"].notna()].copy()
    df = df[df["spread_ratio"] <= SPREAD_RATIO_MAX].copy()

    df["dte"] = (df["expiry_ts"] - asof) / (1000 * 60 * 60 * 24)
    tmin, tmax = _horizon_window(horizon)
    df = df[(df["dte"] >= tmin) & (df["dte"] <= tmax)].copy()

    if view == "up":
        kind = "CALL"
        side = "DEBIT"
        anchor_leg = "K2"
    elif view == "not_up":
        kind = "CALL"
        side = "CREDIT"
        anchor_leg = "K1"
    elif view == "down":
        kind = "PUT"
        side = "DEBIT"
        anchor_leg = "K1"
    else:
        kind = "PUT"
        side = "CREDIT"
        anchor_leg = "K1"

    empty_base = {
        **_empty_scan_result(meta, df, horizon=horizon, view=view, side=side, anchor_leg=anchor_leg, anchor_strike=target_price),
        "items": [],
        "notes": {"strike_snapped": False, "original_target": target_price},
    }
    if df.empty:
        return empty_base

    df = df[df["option_type"].str.upper() == ("C" if kind == "CALL" else "P")].copy()
    if df.empty:
        return empty_base

    candidates = []
    strike_snapped = False

    all_strikes = sorted(df["strike"].unique())
    if len(all_strikes) == 0:
        return empty_base

    unified_anchor_strike, _, was_snapped = _snap_to_grid(target_price, np.array(all_strikes))
    if was_snapped:
        strike_snapped = True

    for exp_ts, grp in df.groupby("expiry_ts"):
        grp = grp.sort_values("strike")
        strikes = grp["strike"].values
        mids = grp["mid"].values
        ivs = grp["mark_iv"].values
        s_vals = grp["underlying"].values
        qflags = grp["quality_flag"].values

        s = float(np.nanmean(s_vals)) if len(s_vals) else float("nan")
        iv = float(np.nanmean(ivs)) if len(ivs) else float("nan")
        t_years = max(((exp_ts - asof) / (1000 * 60 * 60 * 24)) / 365.0, 1e-6)

        iv_at = None
        params = (svi_surface or {}).get(int(exp_ts))
        if params is not None:
            k_grid = np.log(strikes / max(s, 1e-9))
            iv_grid = svi_iv(k_grid, params, t_years)
            iv_at = lambda kb, _sg=strikes, _ig=iv_grid: float(np.interp(kb, _sg, _ig))

        buy_arr, sell_arr = _buy_sell_arrays(grp, mids, pricing_mode)

        anchor_idx_arr = np.where(strikes == unified_anchor_strike)[0]
        if len(anchor_idx_arr) == 0:
            continue

        anchor_idx = int(anchor_idx_arr[0])
        anchor_strike = unified_anchor_strike
        # 锚定腿价格按角色取价：up/not_up/not_down 锚为卖腿，down 锚为买腿
        anchor_px = float(buy_arr[anchor_idx] if view == "down" else sell_arr[anchor_idx])

        if qflags[anchor_idx] in ("missing", "invalid"):
            continue

        if view == "up":
            if anchor_strike < s:
                continue
            for i in range(max(0, anchor_idx - max_gap_steps), anchor_idx):
                k1 = float(strikes[i])
                if k1 >= anchor_strike:
                    continue
                if qflags[i] in ("missing", "invalid"):
                    continue
                m1 = float(buy_arr[i])
                metrics = _calc_vertical_metrics("CALL", "DEBIT", k1, anchor_strike, long_px=m1, short_px=anchor_px, s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < MIN_PREMIUM_USD or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue
                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d"),
                    "K1": k1, "K2": anchor_strike,
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        elif view == "down":
            if anchor_strike > s:
                continue
            for i in range(max(0, anchor_idx - max_gap_steps), anchor_idx):
                k2 = float(strikes[i])
                if k2 >= anchor_strike:
                    continue
                if qflags[i] in ("missing", "invalid"):
                    continue
                m2 = float(sell_arr[i])
                metrics = _calc_vertical_metrics("PUT", "DEBIT", anchor_strike, k2, long_px=anchor_px, short_px=m2, s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < MIN_PREMIUM_USD or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue
                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d"),
                    "K1": anchor_strike, "K2": k2,
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        elif view == "not_up":
            if anchor_strike < s:
                continue
            for i in range(anchor_idx + 1, min(len(strikes), anchor_idx + max_gap_steps + 1)):
                k2 = float(strikes[i])
                if k2 <= anchor_strike or k2 < s:
                    continue
                if qflags[i] in ("missing", "invalid"):
                    continue
                m2 = float(buy_arr[i])
                metrics = _calc_vertical_metrics("CALL", "CREDIT", anchor_strike, k2, long_px=m2, short_px=anchor_px, s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < MIN_PREMIUM_USD or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue
                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d"),
                    "K1": anchor_strike, "K2": k2,
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

        else:
            if anchor_strike > s:
                continue
            for i in range(max(0, anchor_idx - max_gap_steps), anchor_idx):
                k2 = float(strikes[i])
                if k2 >= anchor_strike or k2 > s:
                    continue
                if qflags[i] in ("missing", "invalid"):
                    continue
                m2 = float(buy_arr[i])
                metrics = _calc_vertical_metrics("PUT", "CREDIT", anchor_strike, k2, long_px=m2, short_px=anchor_px, s=s, iv=iv, t_years=t_years, iv_at=iv_at)
                premium_usd = abs(metrics["premium"]) * s
                if premium_usd < MIN_PREMIUM_USD or math.isnan(metrics["odds"]) or metrics["odds"] == float("inf"):
                    continue
                candidates.append({
                    "expiry_ts": int(exp_ts),
                    "expiry_date": pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d"),
                    "K1": anchor_strike, "K2": k2,
                    "premium": metrics["premium"],
                    "max_profit": metrics["max_profit"],
                    "max_loss": metrics["max_loss"],
                    "odds": metrics["odds"],
                })

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

    logger.info("Opinion scan base=%s view=%s horizon=%s results=%d", base, view, horizon, len(top_strategies))

    return {
        **_empty_scan_result(meta, df, horizon=horizon, view=view, side=side, anchor_leg=anchor_leg, anchor_strike=unified_anchor_strike),
        "items": top_strategies,
        "notes": {
            "strike_snapped": strike_snapped,
            "original_target": target_price,
        },
    }
