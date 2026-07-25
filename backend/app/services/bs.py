from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import norm


def _norm_cdf(x: float) -> float:
    return norm.cdf(x)


def probability_st_ge_k(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    """P(S_T ≥ K)：BS 风险中性下到期不低于 K 的概率 = N(d2)。

    注：d2 = (ln(S/K) + (r−σ²/2)T) / (σ√T)。K→∞ 时 d2→−∞，概率→0。
    """
    if s <= 0 or k <= 0 or vol <= 0 or t_years <= 0:
        return float("nan")
    vt = vol * math.sqrt(t_years)
    d2 = (math.log(s / k) + (r - 0.5 * vol * vol) * t_years) / vt
    return _norm_cdf(d2)


def probability_st_le_k(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    p = probability_st_ge_k(s, k, vol, t_years, r)
    if math.isnan(p):
        return p
    return 1.0 - p


def pop_for_vertical(
    kind: str, side: str, s: float, k1: float, k2: float,
    premium: float, vol: float, t_years: float, r: float = 0.0,
) -> Optional[float]:
    k = None
    kind_u = kind.upper()
    side_u = side.upper()

    if kind_u == "CALL":
        k = (k1 + premium)
        if side_u == "DEBIT":
            return probability_st_ge_k(s, k, vol, t_years, r)
        else:
            return probability_st_le_k(s, k, vol, t_years, r)
    else:
        k = (k2 - premium)
        if side_u == "DEBIT":
            return probability_st_le_k(s, k, vol, t_years, r)
        else:
            return probability_st_ge_k(s, k, vol, t_years, r)


def delta_call(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    if s <= 0 or k <= 0 or vol <= 0 or t_years <= 0:
        return float("nan")
    vt = vol * math.sqrt(t_years)
    d1 = (math.log(s / k) + (r + 0.5 * vol * vol) * t_years) / vt
    return _norm_cdf(d1)


def delta_put(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    return delta_call(s, k, vol, t_years, r) - 1.0


def delta_call_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """向量化版 delta_call：k/vol/t_years 支持数组，一次完成全部计算。

    任一输入非法（s/k/vol/t <= 0）的对应位置返回 NaN，与标量版语义一致。
    """
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        vt = vol * np.sqrt(t)
        d1 = (np.log(s / k) + (r + 0.5 * vol * vol) * t) / vt
        out = np.asarray(norm.cdf(d1), dtype=float)
    bad = (s <= 0) | (k <= 0) | (vol <= 0) | (t <= 0)
    return np.where(bad, np.nan, out)


def delta_put_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """向量化版 delta_put。"""
    return delta_call_vec(s, k, vol, t_years, r) - 1.0


_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _phi(x) -> np.ndarray:
    """标准正态密度 φ(x)，支持数组。"""
    return np.exp(-0.5 * np.asarray(x, dtype=float) ** 2) / _SQRT_2PI


def _d1_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        vt = vol * np.sqrt(t)
        return (np.log(s / k) + (r + 0.5 * vol * vol) * t) / vt


def _bad_mask(s: float, k, vol, t) -> np.ndarray:
    return (s <= 0) | (np.asarray(k, dtype=float) <= 0) | (np.asarray(vol, dtype=float) <= 0) | (np.asarray(t, dtype=float) <= 0)


def vega_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """Vega = S·φ(d1)·√t（call/put 相同），对 1.00 绝对波动率的敏感度。

    例：返回值 500 表示 IV 上升 1.00（100 个波动率点）权利金约涨 500（USD 计价标的）。
    常用「每 1 个波动率点」口径时再 /100。
    """
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = s * _phi(_d1_vec(s, k, vol, t, r)) * np.sqrt(t)
    return np.where(_bad_mask(s, k, vol, t), np.nan, out)


def gamma_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """Gamma = φ(d1) / (S·σ·√t)（call/put 相同）。"""
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = _phi(_d1_vec(s, k, vol, t, r)) / (s * vol * np.sqrt(t))
    return np.where(_bad_mask(s, k, vol, t), np.nan, out)


def theta_vec(s: float, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """Theta（每个自然日）= −S·φ(d1)·σ / (2√t) / 365（r=0 时 call/put 相同）。

    返回每日时间衰减（标的价格单位/天），卖方策略看其绝对值。
    """
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = -s * _phi(_d1_vec(s, k, vol, t, r)) * vol / (2.0 * np.sqrt(t)) / 365.0
    return np.where(_bad_mask(s, k, vol, t), np.nan, out)


def prob_between(s: float, k_lo: float, k_hi: float, vol: float, t_years: float, r: float = 0.0) -> float:
    """P(S_T ∈ [k_lo, k_hi])：到期落在区间的概率（对数正态）。

    铁秃鹰 / 卖出宽跨的 PoP 即此函数在两盈亏平衡点之间的取值。
    """
    if k_hi <= k_lo or k_lo <= 0:
        return float("nan")
    p_lo = probability_st_ge_k(s, k_lo, vol, t_years, r)
    p_hi = probability_st_ge_k(s, k_hi, vol, t_years, r)
    if math.isnan(p_lo) or math.isnan(p_hi):
        return float("nan")
    return p_lo - p_hi


def strike_from_delta_vec(s: float, call_delta, vol, t_years, r: float = 0.0) -> np.ndarray:
    """按 call delta 目标值反解行权价：K = S·exp(−d1*·σ√t + (r+0.5σ²)t)。

    call_delta ∈ (0,1)；定位 put 腿时传 1−|Δp|（put Δ = call Δ − 1）。
    非法输入返回 NaN。用于「在 SVI 曲线上定位 25Δ 行权价」等场景。
    """
    d = np.asarray(call_delta, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1_star = norm.ppf(d)
        out = s * np.exp(-d1_star * vol * np.sqrt(t) + (r + 0.5 * vol * vol) * t)
    bad = (s <= 0) | (d <= 0) | (d >= 1) | (vol <= 0) | (t <= 0)
    return np.where(bad, np.nan, out)


def strike_from_delta(s: float, target_delta: float, vol: float, t_years: float,
                      kind: str = "call", r: float = 0.0) -> float:
    """标量版按 delta 反解行权价。

    kind="call": target_delta ∈ (0,1)；kind="put": target_delta ∈ (−1,0)。
    """
    if kind.lower() == "put":
        if not (-1.0 < target_delta < 0.0):
            return float("nan")
        call_delta = 1.0 + target_delta  # put Δ = call Δ − 1
    else:
        if not (0.0 < target_delta < 1.0):
            return float("nan")
        call_delta = target_delta
    out = strike_from_delta_vec(s, call_delta, vol, t_years, r)
    return float(out)


def price_call_vec(s, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """BS call 价格（向量化，r=0）：S·N(d1) − K·N(d2)。

    s/k/vol/t_years 均可为数组（broadcast）。单位与 s、k 一致（USD），
    Deribit 币本位报价 = 本结果 / s。非法输入返回 NaN。
    """
    s = np.asarray(s, dtype=float)
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        vt = vol * np.sqrt(t)
        d1 = (np.log(s / k) + (r + 0.5 * vol * vol) * t) / vt
        d2 = d1 - vt
        out = s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
    bad = (s <= 0) | (k <= 0) | (vol <= 0) | (t <= 0)
    return np.where(bad, np.nan, out)


def price_put_vec(s, k, vol, t_years, r: float = 0.0) -> np.ndarray:
    """BS put 价格（向量化，r=0）：K·N(−d2) − S·N(−d1)。语义同 price_call_vec。"""
    s = np.asarray(s, dtype=float)
    k = np.asarray(k, dtype=float)
    vol = np.asarray(vol, dtype=float)
    t = np.asarray(t_years, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        vt = vol * np.sqrt(t)
        d1 = (np.log(s / k) + (r + 0.5 * vol * vol) * t) / vt
        d2 = d1 - vt
        out = k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)
    bad = (s <= 0) | (k <= 0) | (vol <= 0) | (t <= 0)
    return np.where(bad, np.nan, out)
