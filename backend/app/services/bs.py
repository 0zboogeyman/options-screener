from __future__ import annotations

import math
from typing import Optional

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
