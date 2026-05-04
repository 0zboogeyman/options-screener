from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from .quality import compute_mid, spread_flag


def _nan_to_none(x: Optional[float]) -> Optional[float]:
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x


def _compute_spread_ratio(bid: Optional[float], ask: Optional[float]) -> float:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return float("inf")
    mid_price = (bid + ask) / 2.0
    if mid_price <= 0:
        return float("inf")
    return (ask - bid) / mid_price


def prep_chain(df: pd.DataFrame) -> pd.DataFrame:
    req = [
        "date", "base", "instrument", "expiry_ts", "strike", "option_type",
        "bid", "ask", "mark_price", "mark_iv", "underlying", "oi", "asof_ts",
    ]
    for c in req:
        if c not in df.columns:
            df[c] = np.nan

    bids = df["bid"].tolist()
    asks = df["ask"].tolist()
    marks = df["mark_price"].tolist()

    mids = []
    qflags = []
    spread_ratios = []
    for bid, ask, mark in zip(bids, asks, marks):
        b = _nan_to_none(bid)
        a = _nan_to_none(ask)
        m = _nan_to_none(mark)
        mid = compute_mid(b, a, m)
        mids.append(mid)
        qflags.append(spread_flag(b, a, mid))
        spread_ratios.append(_compute_spread_ratio(b, a))

    df = df.copy()
    df["mid"] = mids
    df["quality_flag"] = qflags
    df["spread_ratio"] = spread_ratios
    return df
