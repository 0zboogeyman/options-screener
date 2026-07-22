from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import norm


def _norm_cdf(x: float) -> float:
    return norm.cdf(x)


def probability_st_ge_k(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    if s <= 0 or k <= 0 or vol <= 0 or t_years <= 0:
        return float("nan")
    vt = vol * math.sqrt(t_years)
    d2 = (math.log(s / k) + (r - 0.5 * vol * vol) * t_years) / vt
    return 1.0 - _norm_cdf(d2)


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
