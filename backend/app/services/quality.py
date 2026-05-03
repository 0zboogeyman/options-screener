from __future__ import annotations

from typing import Optional


def compute_mid(bid: Optional[float], ask: Optional[float], mark: Optional[float]) -> Optional[float]:
    if bid is not None and ask is not None:
        return 0.5 * (bid + ask)
    if mark is not None:
        return mark
    if bid is not None:
        return bid
    if ask is not None:
        return ask
    return None


def spread_flag(bid: Optional[float], ask: Optional[float], mid: Optional[float], threshold: float = 0.15) -> str:
    if bid is None or ask is None or mid is None or mid <= 0:
        return "missing"
    if ask < bid:
        return "invalid"
    width = ask - bid
    if width / mid > threshold:
        return "wide_spread"
    return "ok"

