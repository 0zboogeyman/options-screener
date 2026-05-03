from __future__ import annotations

import math


SQRT_2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    # Abramowitz-Stegun approximation via erf for simplicity
    return 0.5 * (1.0 + math.erf(x / SQRT_2))


def probability_st_ge_k(s: float, k: float, vol: float, t_years: float, r: float = 0.0) -> float:
    """Risk-neutral P(S_T >= K). Uses lognormal with drift r.
    Returns value in [0,1]. If inputs invalid, returns NaN.
    """
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
    kind: str,
    side: str,
    s: float,
    k1: float,
    k2: float,
    premium: float,
    vol: float,
    t_years: float,
    r: float = 0.0,
) -> float:
    """Approximate POP (P[net PnL >= 0]) for a vertical spread via BEP threshold.

    Assumptions:
    - Break-even (BEP) threshold is used; vertical cap does not change the sign region.
    - For calls: BEP_call_debit = K1 + premium; BEP_call_credit = K1 + premium.
    - For puts:  BEP_put_debit  = K2 - premium; BEP_put_credit  = K2 - premium.

    kind: "CALL" or "PUT"
    side: "DEBIT" or "CREDIT"
    """
    k = None
    kind_u = kind.upper()
    side_u = side.upper()

    if kind_u == "CALL":
        # Debit: long K1, short K2. Credit: short K1, long K2.
        k = (k1 + premium)
        if side_u == "DEBIT":
            return probability_st_ge_k(s, k, vol, t_years, r)
        else:
            return probability_st_le_k(s, k, vol, t_years, r)
    else:  # PUT
        k = (k2 - premium)
        if side_u == "DEBIT":
            return probability_st_le_k(s, k, vol, t_years, r)
        else:
            return probability_st_ge_k(s, k, vol, t_years, r)

