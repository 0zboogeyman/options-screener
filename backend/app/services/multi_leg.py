"""多腿策略扫描器：铁秃鹰 / 宽跨（双侧）/ 日历价差。

共同约定：
  * 腿 IV 一律取 SVI 拟合曲线（逐行权价），切片无 ok SVI 时该到期跳过
    （RND 依赖 SVI，无法降级到单腿 mark_iv 而不损一致性）；
  * PoP / 尾部风险由 RND（Breeden-Litzenberger 隐含密度）计算，含微笑肥尾；
  * 权利金/贷记以币种计，USD 口径按即期 S 换算（与 margin.py 一致，estimate）；
  * pricing_mode="mid" 用中间价；"conservative" 用可执行价（卖腿 bid、买腿 ask）；
  * 评分为 0-100 加权归一（与 single_leg 同体系），权重常量见各策略。
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import margin as margin_mod
from .bs import (
    delta_call_vec,
    price_call_vec,
    price_put_vec,
    theta_vec,
    vega_vec,
)
from .preprocessing import prep_chain
from .rnd import (
    expected_shortfall,
    expected_upside_tail,
    prob_between as rnd_prob_between,
    prob_ge as rnd_prob_ge,
    rnd_from_svi,
)
from .scanner import SPREAD_RATIO_MAX
from .single_leg import _normalize_score
from .svi import svi_iv

logger = logging.getLogger(__name__)

MS_PER_DAY = 1000 * 60 * 60 * 24

# 评分权重（字段, 权重, 是否取反）
IC_SCORE_WEIGHTS: Tuple = (
    ("apr_on_max_loss", 0.35, False),
    ("pop", 0.30, False),
    ("liquidity_score", 0.20, False),
    ("ivp_score", 0.15, False),
)
STRANGLE_SHORT_WEIGHTS: Tuple = (
    ("apr_on_im", 0.30, False),
    ("pop", 0.30, False),
    ("liquidity_score", 0.20, False),
    ("ivp_score", 0.20, False),
)
STRANGLE_LONG_WEIGHTS: Tuple = (
    ("cost_ratio", 0.35, True),       # 成本/预期波动，越低越好
    ("pop_profit", 0.25, False),
    ("vega_per_dollar", 0.20, False),
    ("liquidity_score", 0.20, False),
)
CALENDAR_SCORE_WEIGHTS: Tuple = (
    ("theta_apr", 0.35, False),
    ("iv_slope_ratio", 0.25, False),
    ("liquidity_score", 0.20, False),
    ("debit_ratio", 0.20, True),      # 权利金/远月预期波动，越低越好
)


# ---------------------------------------------------------------------------
# 公共准备
# ---------------------------------------------------------------------------

def _prepare_legs(chain_df: pd.DataFrame, meta, min_oi: int) -> Tuple[pd.DataFrame, int]:
    df = prep_chain(chain_df)
    df = df[df["mid"].notna()].copy()
    df = df[df["spread_ratio"] <= SPREAD_RATIO_MAX].copy()
    if min_oi > 0:
        df = df[df["oi"].fillna(0) >= min_oi].copy()
    asof = int(meta.asof_ts)
    df["dte"] = (df["expiry_ts"] - asof) / MS_PER_DAY
    df = df[df["dte"] > 0].copy()
    return df, asof


def _enrich_expiry(grp: pd.DataFrame, asof: int, svi_params: Dict) -> pd.DataFrame:
    """给单到期切片补 forward / t_years / svi_iv / delta_c / delta_p。"""
    grp = grp.sort_values("strike").reset_index(drop=True).copy()
    f = float(pd.to_numeric(grp["underlying"], errors="coerce").median())
    exp_ts = int(grp["expiry_ts"].iloc[0])
    t_years = max((exp_ts - asof) / MS_PER_DAY / 365.0, 1e-6)
    strikes = grp["strike"].to_numpy(dtype=float)
    k = np.log(strikes / max(f, 1e-9))
    iv = svi_iv(k, svi_params, t_years)
    # SVI 曲线外推区可能失真，限制在合理范围
    iv = np.clip(iv, 0.01, 3.0)
    delta_c = delta_call_vec(f, strikes, iv, t_years)
    grp["forward"] = f
    grp["t_years"] = t_years
    grp["svi_iv"] = iv
    grp["delta_c"] = delta_c
    grp["delta_p"] = delta_c - 1.0
    return grp


def _exec_prices(grp: pd.DataFrame, pricing_mode: str) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (buy_px, sell_px)：按 pricing_mode 取可执行价或中间价。

    conservative：买入付 ask、卖出收 bid（缺边报价回退 mid）。
    """
    mid = grp["mid"].to_numpy(dtype=float)
    if pricing_mode != "conservative":
        return mid, mid
    bid = pd.to_numeric(grp["bid"], errors="coerce").to_numpy(dtype=float)
    ask = pd.to_numeric(grp["ask"], errors="coerce").to_numpy(dtype=float)
    buy = np.where(np.isfinite(ask) & (ask > 0), ask, mid)
    sell = np.where(np.isfinite(bid) & (bid > 0), bid, mid)
    return buy, sell


def _leg_dict(row: pd.Series, option_kind: str, side: str, price: float) -> Dict:
    return {
        "instrument": row["instrument"],
        "kind": option_kind,   # "PUT" / "CALL"
        "side": side,          # "buy" / "sell"
        "strike": float(row["strike"]),
        "price": float(price),
        "delta": float(row["delta_c"] if option_kind == "CALL" else row["delta_p"]),
        "iv": float(row["svi_iv"]),
        "oi": float(row["oi"]) if np.isfinite(row.get("oi", np.nan)) else 0.0,
        "spread_bps": float(row["spread_ratio"]) * 10000,
    }


def _liquidity_score(legs: List[Dict]) -> float:
    """组合流动性：最差腿的 OI 取对数，按平均点差惩罚。"""
    min_oi = min(l["oi"] for l in legs)
    avg_bps = float(np.mean([l["spread_bps"] for l in legs]))
    return float(np.log1p(min_oi) / (1.0 + avg_bps / 100.0))


def _net_greeks(legs: List[Dict], s: float) -> Dict:
    """组合净希腊字母（delta 张数、vega/theta 为 USD 口径）。"""
    net_delta = sum((1 if l["side"] == "buy" else -1) * l["delta"] for l in legs)
    net_vega = 0.0
    net_theta = 0.0
    for l in legs:
        sign = 1.0 if l["side"] == "buy" else -1.0
        t = l.get("t_years")
        if not t:
            continue
        v = vega_vec(s, l["strike"], l["iv"], t)
        th = theta_vec(s, l["strike"], l["iv"], t)
        net_vega += sign * float(v)
        net_theta += sign * float(th)
    return {"net_delta": float(net_delta), "net_vega_usd": net_vega, "net_theta_usd": net_theta}


def _apply_scores(candidates: List[Dict], weights: Tuple) -> None:
    totals = [0.0] * len(candidates)
    for key, weight, invert in weights:
        raw = []
        for c in candidates:
            v = c.get(key)
            if v is None or not np.isfinite(v):
                v = 0.5 if key == "ivp_score" else np.nan
            raw.append((1.0 - v) if invert and np.isfinite(v) else v)
        norm = _normalize_score(raw)
        for i in range(len(candidates)):
            totals[i] += weight * norm[i]
    for i, c in enumerate(candidates):
        c["score"] = round(totals[i] * 100, 1)
    candidates.sort(key=lambda x: x["score"], reverse=True)


def _empty_result(meta, chain_df, strategy: str, **extra) -> Dict:
    base = chain_df["base"].iloc[0] if not chain_df.empty else ""
    return {
        "asof_date": meta.date,
        "asof_ts": int(meta.asof_ts),
        "base": base,
        "spot_price": meta.spot_price,
        "strategy": strategy,
        **extra,
    }


# ---------------------------------------------------------------------------
# 铁秃鹰
# ---------------------------------------------------------------------------

def scan_iron_condor(
    chain_df: pd.DataFrame,
    meta,
    svi_surface: Optional[Dict[int, Dict]] = None,
    *,
    dte_min: int = 14,
    dte_max: int = 60,
    short_delta_min: float = 0.10,
    short_delta_max: float = 0.25,
    max_wing_steps: int = 5,
    min_credit_usd: float = 20.0,
    min_oi: int = 10,
    pricing_mode: str = "mid",
    top_pool: int = 15,
    return_count: int = 20,
    ivp: Optional[float] = None,
) -> Dict:
    """铁秃鹰：同一到期卖 OTM put 价差 + 卖 OTM call 价差。

    短腿按 SVI-delta 定位（|Δ|∈[short_delta_min, short_delta_max]），
    两侧各取 roi 最高的 top_pool 个价差再两两组合。
    """
    svi_surface = svi_surface or {}
    spot = meta.spot_price
    ivp_score = ivp if ivp is not None else 0.5
    filters = {
        "dte_min": dte_min, "dte_max": dte_max,
        "short_delta_range": [short_delta_min, short_delta_max],
        "max_wing_steps": max_wing_steps, "min_credit_usd": min_credit_usd,
        "min_oi": min_oi, "pricing_mode": pricing_mode,
    }
    if not spot:
        return _empty_result(meta, chain_df, "IRON_CONDOR", filters=filters, candidates=[], ivp=ivp)

    df, asof = _prepare_legs(chain_df, meta, min_oi)
    candidates: List[Dict] = []

    for exp_ts, grp_raw in df.groupby("expiry_ts"):
        params = svi_surface.get(int(exp_ts))
        if params is None:
            continue
        dte = (exp_ts - asof) / MS_PER_DAY
        if dte < dte_min or dte > dte_max:
            continue
        grp = _enrich_expiry(grp_raw, asof, params)
        s = float(grp["forward"].iloc[0])
        t_years = float(grp["t_years"].iloc[0])
        rnd = rnd_from_svi(params, t_years, s)
        buy_px, sell_px = _exec_prices(grp, pricing_mode)

        puts = grp[grp["option_type"].str.upper() == "P"].reset_index(drop=True)
        calls = grp[grp["option_type"].str.upper() == "C"].reset_index(drop=True)
        pb = buy_px[grp["option_type"].str.upper() == "P"]
        ps = sell_px[grp["option_type"].str.upper() == "P"]
        cb = buy_px[grp["option_type"].str.upper() == "C"]
        cs = sell_px[grp["option_type"].str.upper() == "C"]

        def _spread_pool(sub: pd.DataFrame, buy: np.ndarray, sell: np.ndarray,
                         kind: str) -> List[Dict]:
            """OTM 贷方价差池：put 侧 short 高 K / long 低 K；call 侧相反。"""
            pool = []
            n = len(sub)
            for i in range(n):
                row_s = sub.iloc[i]
                d = float(row_s["delta_p"] if kind == "PUT" else row_s["delta_c"])
                ad = abs(d)
                if ad < short_delta_min or ad > short_delta_max:
                    continue
                for j in range(1, max_wing_steps + 1):
                    idx = i - j if kind == "PUT" else i + j  # 更虚值的方向
                    if idx < 0 or idx >= n:
                        break
                    row_l = sub.iloc[idx]
                    credit = float(sell[i] - buy[idx])
                    if credit <= 0:
                        continue
                    width = abs(float(row_s["strike"]) - float(row_l["strike"]))
                    credit_usd = credit * s
                    max_loss = width - credit_usd
                    if max_loss <= 0:
                        continue
                    pool.append({
                        "short_row": row_s, "long_row": row_l,
                        "short_px": float(sell[i]), "long_px": float(buy[idx]),
                        "credit": credit, "width_usd": width,
                        "roi": credit_usd / max_loss,
                    })
            pool.sort(key=lambda x: x["roi"], reverse=True)
            return pool[:top_pool]

        put_pool = _spread_pool(puts, pb, ps, "PUT")
        call_pool = _spread_pool(calls, cb, cs, "CALL")

        expiry_date = pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d")
        for pspr in put_pool:
            for cspr in call_pool:
                credit = pspr["credit"] + cspr["credit"]
                credit_usd = credit * s
                if credit_usd < min_credit_usd:
                    continue
                max_loss_usd = max(pspr["width_usd"], cspr["width_usd"]) - credit_usd
                if max_loss_usd <= 0:
                    continue
                be_lo = float(pspr["short_row"]["strike"]) - credit_usd
                be_hi = float(cspr["short_row"]["strike"]) + credit_usd
                pop = rnd_prob_between(rnd, be_lo, be_hi)
                if not np.isfinite(pop):
                    continue

                legs = [
                    _leg_dict(pspr["long_row"], "PUT", "buy", pspr["long_px"]),
                    _leg_dict(pspr["short_row"], "PUT", "sell", pspr["short_px"]),
                    _leg_dict(cspr["short_row"], "CALL", "sell", cspr["short_px"]),
                    _leg_dict(cspr["long_row"], "CALL", "buy", cspr["long_px"]),
                ]
                for l in legs:
                    l["t_years"] = t_years
                mg = margin_mod.margin_iron_condor(
                    s,
                    legs[0]["strike"], legs[1]["strike"],
                    legs[2]["strike"], legs[3]["strike"],
                    legs[1]["price"], legs[0]["price"],
                    legs[2]["price"], legs[3]["price"],
                )
                roi = credit_usd / max_loss_usd
                candidates.append({
                    "expiry_date": expiry_date,
                    "expiry_ts": int(exp_ts),
                    "dte": round(dte, 1),
                    "legs": legs,
                    "strikes": [l["strike"] for l in legs],
                    "credit": credit,
                    "credit_usd": credit_usd,
                    "max_loss_usd": max_loss_usd,
                    "breakeven_lo": be_lo,
                    "breakeven_hi": be_hi,
                    "pop": float(pop),
                    "roi_on_max_loss": roi,
                    "apr_on_max_loss": roi * 365.0 / dte,
                    "im_standard_usd": mg["im_standard_usd"],
                    "liquidity_score": _liquidity_score(legs),
                    "ivp_score": ivp_score,
                    "greeks": _net_greeks(legs, s),
                })

    _apply_scores(candidates, IC_SCORE_WEIGHTS)
    top = candidates[:return_count]
    logger.info("IC scan base=%s results=%d", chain_df["base"].iloc[0] if not chain_df.empty else "", len(top))
    return {
        **_empty_result(meta, chain_df, "IRON_CONDOR", filters=filters),
        "dvol_index": meta.dvol_index,
        "ivp": ivp,
        "candidates": top,
    }


# ---------------------------------------------------------------------------
# 宽跨（long/short 双侧）
# ---------------------------------------------------------------------------

def scan_strangle(
    chain_df: pd.DataFrame,
    meta,
    svi_surface: Optional[Dict[int, Dict]] = None,
    *,
    side: str = "both",
    dte_min: int = 7,
    dte_max: int = 45,
    delta_min: float = 0.10,
    delta_max: float = 0.30,
    max_pool: int = 20,
    min_oi: int = 10,
    pricing_mode: str = "mid",
    return_count: int = 15,
    ivp: Optional[float] = None,
) -> Dict:
    """宽跨：同到期 OTM put + OTM call 组合，long/short 双侧分别评分返回。

    long：做多波动——看 成本/预期波动（cost_ratio）、获利概率、vega 效率；
    short：做空波动——看 PoP、APR on IM、RND 尾部风险（5% ES 亏损估计）。
    """
    svi_surface = svi_surface or {}
    spot = meta.spot_price
    filters = {
        "side": side, "dte_min": dte_min, "dte_max": dte_max,
        "delta_range": [delta_min, delta_max], "min_oi": min_oi,
        "pricing_mode": pricing_mode,
    }
    if not spot:
        return _empty_result(meta, chain_df, "STRANGLE", filters=filters,
                             ivp=ivp, long=[], short=[])

    df, asof = _prepare_legs(chain_df, meta, min_oi)
    longs: List[Dict] = []
    shorts: List[Dict] = []

    for exp_ts, grp_raw in df.groupby("expiry_ts"):
        params = svi_surface.get(int(exp_ts))
        if params is None:
            continue
        dte = (exp_ts - asof) / MS_PER_DAY
        if dte < dte_min or dte > dte_max:
            continue
        grp = _enrich_expiry(grp_raw, asof, params)
        s = float(grp["forward"].iloc[0])
        t_years = float(grp["t_years"].iloc[0])
        rnd = rnd_from_svi(params, t_years, s)
        buy_px, sell_px = _exec_prices(grp, pricing_mode)
        grp = grp.assign(_buy=buy_px, _sell=sell_px)

        puts = grp[(grp["option_type"].str.upper() == "P")
                   & (grp["delta_p"].abs() >= delta_min) & (grp["delta_p"].abs() <= delta_max)]
        calls = grp[(grp["option_type"].str.upper() == "C")
                    & (grp["delta_c"] >= delta_min) & (grp["delta_c"] <= delta_max)]
        # 池上限：按 OI 取前 max_pool，控制组合规模
        puts = puts.sort_values("oi", ascending=False).head(max_pool)
        calls = calls.sort_values("oi", ascending=False).head(max_pool)
        if puts.empty or calls.empty:
            continue

        atm_iv = float(params["atm_iv"]) if params.get("atm_iv") else float(np.nanmean(grp["svi_iv"]))
        expected_move = s * atm_iv * math.sqrt(t_years)
        expiry_date = pd.Timestamp(exp_ts, unit="ms").strftime("%Y-%m-%d")

        for _, pr in puts.iterrows():
            for _, cr in calls.iterrows():
                legs_long = [
                    _leg_dict(pr, "PUT", "buy", float(pr["_buy"])),
                    _leg_dict(cr, "CALL", "buy", float(cr["_buy"])),
                ]
                for l in legs_long:
                    l["t_years"] = t_years
                k_put, k_call = legs_long[0]["strike"], legs_long[1]["strike"]

                if side in ("both", "long"):
                    cost = legs_long[0]["price"] + legs_long[1]["price"]
                    cost_usd = cost * s
                    if cost_usd > 0:
                        be_lo = k_put - cost_usd
                        be_hi = k_call + cost_usd
                        pop_profit = (1.0 - rnd_prob_ge(rnd, be_lo)) + rnd_prob_ge(rnd, be_hi)
                        g = _net_greeks(legs_long, s)
                        longs.append({
                            "expiry_date": expiry_date, "expiry_ts": int(exp_ts), "dte": round(dte, 1),
                            "legs": legs_long,
                            "strikes": [k_put, k_call],
                            "cost": cost, "cost_usd": cost_usd,
                            "breakeven_lo": be_lo, "breakeven_hi": be_hi,
                            "move_required_pct": max(be_hi - s, s - be_lo) / s,
                            "pop_profit": float(pop_profit),
                            "cost_ratio": cost_usd / max(expected_move, 1e-9),
                            "vega_per_dollar": g["net_vega_usd"] / cost_usd,
                            "greeks": g,
                            "liquidity_score": _liquidity_score(legs_long),
                        })

                if side in ("both", "short"):
                    legs_short = [
                        _leg_dict(pr, "PUT", "sell", float(pr["_sell"])),
                        _leg_dict(cr, "CALL", "sell", float(cr["_sell"])),
                    ]
                    for l in legs_short:
                        l["t_years"] = t_years
                    credit = legs_short[0]["price"] + legs_short[1]["price"]
                    credit_usd = credit * s
                    if credit_usd > 0:
                        be_lo_s = k_put - credit_usd
                        be_hi_s = k_call + credit_usd
                        pop = rnd_prob_between(rnd, be_lo_s, be_hi_s)
                        mg = margin_mod.margin_strangle_short(
                            s, k_put, k_call, legs_short[0]["price"], legs_short[1]["price"])
                        apr_on_im = (credit / mg["im_standard"]) * 365.0 / dte if mg["im_standard"] else None
                        # 尾部风险：5% 期望亏损价位对应的估计亏损（USD）
                        es_lo = expected_shortfall(rnd, 0.05)
                        es_hi = expected_upside_tail(rnd, 0.05)
                        tail_loss_put = max(k_put - es_lo, 0.0) - credit_usd
                        tail_loss_call = max(es_hi - k_call, 0.0) - credit_usd
                        g = _net_greeks(legs_short, s)
                        shorts.append({
                            "expiry_date": expiry_date, "expiry_ts": int(exp_ts), "dte": round(dte, 1),
                            "legs": legs_short,
                            "strikes": [k_put, k_call],
                            "credit": credit, "credit_usd": credit_usd,
                            "breakeven_lo": be_lo_s, "breakeven_hi": be_hi_s,
                            "pop": float(pop),
                            "im_standard_usd": mg["im_standard_usd"],
                            "apr_on_im": apr_on_im,
                            "tail_loss_est_usd": float(max(tail_loss_put, tail_loss_call)),
                            "greeks": g,
                            "liquidity_score": _liquidity_score(legs_short),
                            "ivp_score": ivp if ivp is not None else 0.5,
                            "risk_warning": "理论亏损无限，尾部为 RND 5% 期望亏损估计",
                        })

    _apply_scores(longs, STRANGLE_LONG_WEIGHTS)
    _apply_scores(shorts, STRANGLE_SHORT_WEIGHTS)
    logger.info("Strangle scan base=%s long=%d short=%d",
                chain_df["base"].iloc[0] if not chain_df.empty else "", len(longs), len(shorts))
    return {
        **_empty_result(meta, chain_df, "STRANGLE", filters=filters),
        "dvol_index": meta.dvol_index,
        "ivp": ivp,
        "long": longs[:return_count] if side in ("both", "long") else [],
        "short": shorts[:return_count] if side in ("both", "short") else [],
    }


# ---------------------------------------------------------------------------
# 日历价差
# ---------------------------------------------------------------------------

def scan_calendar(
    chain_df: pd.DataFrame,
    meta,
    svi_surface: Optional[Dict[int, Dict]] = None,
    *,
    near_dte_min: int = 7,
    near_dte_max: int = 30,
    min_gap_days: int = 14,
    strike_band_pct: float = 0.10,
    min_oi: int = 10,
    pricing_mode: str = "mid",
    return_count: int = 15,
    ivp: Optional[float] = None,
) -> Dict:
    """日历价差：卖近月 + 买远月同行权价（K≥S 用 CALL，K<S 用 PUT）。

    核心评分：SVI 期限结构斜率（近月 ATM IV − 远月 ATM IV，backwardation 为正）
    + theta 捕获差 + 流动性 + 权利金便宜度。利润区间在近月到期日对
    S_T 网格做数值重定价求解（远月按当前 SVI 曲线剩余期限估值，近似）。
    """
    svi_surface = svi_surface or {}
    spot = meta.spot_price
    filters = {
        "near_dte_range": [near_dte_min, near_dte_max],
        "min_gap_days": min_gap_days, "strike_band_pct": strike_band_pct,
        "min_oi": min_oi, "pricing_mode": pricing_mode,
    }
    if not spot:
        return _empty_result(meta, chain_df, "CALENDAR", filters=filters, candidates=[], ivp=ivp)

    df, asof = _prepare_legs(chain_df, meta, min_oi)

    # 按到期准备切片（含 SVI enrich），仅保留 svi ok 的到期
    slices: List[Dict] = []
    for exp_ts, grp_raw in df.groupby("expiry_ts"):
        params = svi_surface.get(int(exp_ts))
        if params is None:
            continue
        dte = (exp_ts - asof) / MS_PER_DAY
        grp = _enrich_expiry(grp_raw, asof, params)
        buy_px, sell_px = _exec_prices(grp, pricing_mode)
        grp = grp.assign(_buy=buy_px, _sell=sell_px)
        slices.append({"expiry_ts": int(exp_ts), "dte": dte, "grp": grp, "params": params})
    slices.sort(key=lambda x: x["dte"])

    candidates: List[Dict] = []
    for i, near in enumerate(slices):
        if near["dte"] < near_dte_min or near["dte"] > near_dte_max:
            continue
        for far in slices[i + 1:]:
            gap = far["dte"] - near["dte"]
            if gap < min_gap_days:
                continue
            atm_near = float(near["params"]["atm_iv"])
            atm_far = float(far["params"]["atm_iv"])
            iv_slope = atm_near - atm_far
            iv_slope_ratio = iv_slope / max(atm_far, 1e-6)

            s = float(near["grp"]["forward"].iloc[0])
            t_near = float(near["grp"]["t_years"].iloc[0])
            t_far = float(far["grp"]["t_years"].iloc[0])

            # 两到期共有行权价，取 |ln(K/S)| <= band
            near_idx = {float(r["strike"]): r for _, r in near["grp"].iterrows()}
            far_idx = {float(r["strike"]): r for _, r in far["grp"].iterrows()}
            common = sorted(set(near_idx) & set(far_idx))
            for k_strike in common:
                if abs(math.log(k_strike / s)) > strike_band_pct:
                    continue
                kind = "CALL" if k_strike >= s else "PUT"
                rn = near_idx[k_strike]
                rf = far_idx[k_strike]
                sell_px = float(rn["_sell"])
                buy_px = float(rf["_buy"])
                debit = buy_px - sell_px
                debit_usd = debit * s
                if debit_usd <= 0:
                    continue

                th_near = float(theta_vec(s, k_strike, float(rn["svi_iv"]), t_near))
                th_far = float(theta_vec(s, k_strike, float(rf["svi_iv"]), t_far))
                net_theta = -th_near + th_far  # 卖近收 theta、买远付 theta（th 为负值）
                theta_apr = (net_theta / debit_usd) * 365.0 if debit_usd > 0 else None
                vg_near = float(vega_vec(s, k_strike, float(rn["svi_iv"]), t_near))
                vg_far = float(vega_vec(s, k_strike, float(rf["svi_iv"]), t_far))

                legs = [
                    _leg_dict(rn, kind, "sell", sell_px),
                    _leg_dict(rf, kind, "buy", buy_px),
                ]
                legs[0]["t_years"] = t_near
                legs[1]["t_years"] = t_far

                # 近月到期 P&L 数值求解：S_T 网格 ±3σ（近月 ATM 预期波动）
                zone = _calendar_profit_zone(
                    kind, k_strike, debit_usd, t_far - t_near,
                    float(rf["svi_iv"]), s, atm_near, t_near,
                )

                expected_move_far = s * atm_far * math.sqrt(t_far)
                candidates.append({
                    "expiry_near": pd.Timestamp(near["expiry_ts"], unit="ms").strftime("%Y-%m-%d"),
                    "expiry_far": pd.Timestamp(far["expiry_ts"], unit="ms").strftime("%Y-%m-%d"),
                    "expiry_near_ts": near["expiry_ts"],
                    "expiry_far_ts": far["expiry_ts"],
                    "dte_near": round(near["dte"], 1),
                    "dte_far": round(far["dte"], 1),
                    "kind": kind,
                    "strike": k_strike,
                    "legs": legs,
                    "debit": debit,
                    "debit_usd": debit_usd,
                    "atm_iv_near": atm_near,
                    "atm_iv_far": atm_far,
                    "iv_slope": iv_slope,
                    "iv_slope_ratio": iv_slope_ratio,
                    "net_theta_usd": net_theta,
                    "theta_apr": theta_apr,
                    "net_vega_usd": vg_far - vg_near,
                    "debit_ratio": debit_usd / max(expected_move_far, 1e-9),
                    "profit_zone": zone,
                    "liquidity_score": _liquidity_score(legs),
                })

    _apply_scores(candidates, CALENDAR_SCORE_WEIGHTS)
    top = candidates[:return_count]
    logger.info("Calendar scan base=%s results=%d",
                chain_df["base"].iloc[0] if not chain_df.empty else "", len(top))
    return {
        **_empty_result(meta, chain_df, "CALENDAR", filters=filters),
        "dvol_index": meta.dvol_index,
        "ivp": ivp,
        "candidates": top,
    }


def _calendar_profit_zone(
    kind: str, k_strike: float, debit_usd: float, t_remain: float,
    iv_far: float, s: float, atm_iv_near: float, t_near: float,
    n_grid: int = 161,
) -> Dict:
    """近月到期日的 P&L 分布数值估计。

    S_T 网格覆盖 ±3σ（近月 ATM IV 预期波动）；远月腿按剩余期限 t_remain、
    当前远月 SVI iv（sticky strike 近似）BS 重定价；近月腿到期按内在价值。
    返回利润区间与最大利润估计；区间不存在时为 None。
    """
    sigma_move = s * atm_iv_near * math.sqrt(t_near)
    lo = max(s - 3.0 * sigma_move, 1e-6)
    hi = s + 3.0 * sigma_move
    grid = np.linspace(lo, hi, n_grid)

    if kind == "CALL":
        far_val = price_call_vec(grid, k_strike, iv_far, t_remain)
        near_val = np.maximum(grid - k_strike, 0.0)
    else:
        far_val = price_put_vec(grid, k_strike, iv_far, t_remain)
        near_val = np.maximum(k_strike - grid, 0.0)

    # P&L（USD）：远月买腿市值 − 近月卖腿赔付 − 期初权利金
    pnl = far_val - near_val - debit_usd
    pnl = np.where(np.isfinite(pnl), pnl, -debit_usd)

    prof_mask = pnl > 0
    out = {"breakeven_lo": None, "breakeven_hi": None,
           "max_profit_est": float(np.max(pnl)), "max_profit_spot": float(grid[int(np.argmax(pnl))])}
    if not np.any(prof_mask):
        return out
    idx = np.where(prof_mask)[0]
    out["breakeven_lo"] = float(grid[idx[0]])
    out["breakeven_hi"] = float(grid[idx[-1]])
    return out
