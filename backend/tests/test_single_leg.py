"""single_leg（CSP/CC）回归测试。

覆盖近期修复点：
  * CSP breakeven 单位修复：premium 已是 USD 口径，breakeven 必须用
    strike − premium（旧版误用币种价 strike − mid，导致单位混用）；
  * spot 空值时提前返回空结果（旧版会对 None 做算术产生 NaN/崩溃）；
  * _apply_scores 过滤掉评分低于 MIN_SCORE 的候选。
"""
from __future__ import annotations

import pytest

from app.services.loader import ChainMeta
from app.services.single_leg import CSP_SCORE_WEIGHTS, MIN_SCORE, _apply_scores, scan_csp

_ASOF = 1784908800000          # 2026-07-26 UTC
_EXPIRY = 1787904000000        # 2026-08-28 UTC，DTE ≈ 34.7 天


def _put_chain(rows=6, start_strike=60000.0, step=2000.0):
    import pandas as pd

    recs = []
    for i in range(rows):
        k = start_strike + i * step
        recs.append({
            "date": "2026-07-26", "base": "BTC",
            "instrument": f"BTC-28AUG26-{int(k)}-P",
            "expiry_ts": _EXPIRY, "strike": float(k), "option_type": "P",
            "bid": 120.0, "ask": 125.0, "mark_price": 122.5, "mark_iv": 0.55,
            "underlying": 64000.0, "oi": 400, "asof_ts": _ASOF,
        })
    return pd.DataFrame(recs)


def _meta(spot=64000.0):
    return ChainMeta(date="2026-07-26", asof_ts=_ASOF, bases=["BTC"], spot_price=spot)


def test_csp_breakeven_uses_usd_premium():
    """breakeven = strike − premium(USD)，单位一致（回归旧版 strike − mid 币种价）。"""
    df = _put_chain()
    r = scan_csp(df, _meta(), max_dte=60, max_delta=0.9, min_oi=0,
                 max_spread_bps=5000, available_cash=100000, return_count=10)
    assert r["candidates"], "构造数据应产出候选"
    for c in r["candidates"]:
        assert c["breakeven"] == pytest.approx(c["strike"] - c["premium"])


def test_csp_empty_spot_returns_empty():
    """spot 缺失时提前返回空结果，不抛异常也不产出 NaN。"""
    df = _put_chain()
    r = scan_csp(df, _meta(spot=None), max_dte=60, max_delta=0.9, min_oi=0,
                 max_spread_bps=5000, available_cash=100000, return_count=10)
    assert r["candidates"] == []
    assert r["spot_price"] is None


def test_apply_scores_filters_below_min_score():
    """评分排序后低于 MIN_SCORE 的候选被原地过滤。"""
    good = {"apr": 0.8, "discount_pct": 0.6, "assign_prob": 0.05, "liquidity_score": 0.9}
    bad = {"apr": 0.01, "discount_pct": 0.01, "assign_prob": 0.95, "liquidity_score": 0.02}
    cands = [dict(good), dict(bad)]
    _apply_scores(cands, CSP_SCORE_WEIGHTS)
    # 高分候选必须保留且分数达标
    assert cands, "至少应保留高分候选"
    assert all(c["score"] >= MIN_SCORE for c in cands)
    assert max(c["score"] for c in cands) > MIN_SCORE
    # 低分候选（如未被过滤）也不得出现在结果前列之外——排序必须是降序
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
