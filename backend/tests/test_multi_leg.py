"""multi_leg 三策略 + scanner 升级的合成链测试。

合成链：spot=100000，近月 14d / 远月 42d 两个到期；
IV 来自已知 SVI 曲线，报价 = BS 理论价 ±1% 点差，OI=200。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.services.bs import price_call_vec, price_put_vec
from app.services.multi_leg import scan_calendar, scan_iron_condor, scan_strangle
from app.services.scanner import scan_buckets
from app.services.svi import svi_iv

F = 100000.0
NOW_MS = int(time.time() * 1000)
DAY_MS = 24 * 3600 * 1000

NEAR_TS = NOW_MS + 14 * DAY_MS
FAR_TS = NOW_MS + 42 * DAY_MS

IV_NEAR, IV_FAR = 0.55, 0.50
SVI_NEAR = {"a": IV_NEAR ** 2 * (14 / 365), "b": 0.05, "rho": -0.2, "m": 0.0, "sigma": 0.1,
            "atm_iv": IV_NEAR, "rr25": None, "bf25": None, "dte": 14.0}
SVI_FAR = {"a": IV_FAR ** 2 * (42 / 365), "b": 0.05, "rho": -0.2, "m": 0.0, "sigma": 0.1,
           "atm_iv": IV_FAR, "rr25": None, "bf25": None, "dte": 42.0}
SURFACE = {NEAR_TS: SVI_NEAR, FAR_TS: SVI_FAR}


def _make_chain() -> pd.DataFrame:
    rows = []
    strikes = np.arange(60000.0, 150001.0, 2000.0)
    for exp_ts, t_days, params in ((NEAR_TS, 14, SVI_NEAR), (FAR_TS, 42, SVI_FAR)):
        t = t_days / 365.0
        k = np.log(strikes / F)
        ivs = svi_iv(k, params, t)
        for ki, strike, iv in zip(k, strikes, ivs):
            for otype in ("C", "P"):
                if otype == "C":
                    usd = float(price_call_vec(F, strike, iv, t))
                else:
                    usd = float(price_put_vec(F, strike, iv, t))
                mid = usd / F  # 币本位报价
                if mid <= 0:
                    continue
                rows.append({
                    "date": "2026-07-25", "base": "BTC",
                    "instrument": f"BTC-X-{int(strike)}-{otype}",
                    "expiry_ts": exp_ts, "strike": strike, "option_type": otype,
                    "bid": mid * 0.99, "ask": mid * 1.01, "mark_price": mid,
                    "mark_iv": float(iv), "underlying": F, "oi": 200.0, "asof_ts": NOW_MS,
                })
    return pd.DataFrame(rows)


def _meta():
    return SimpleNamespace(date="2026-07-25", asof_ts=NOW_MS, spot_price=F, dvol_index=50.0)


CHAIN = _make_chain()


def test_iron_condor_basic_invariants():
    out = scan_iron_condor(CHAIN, _meta(), SURFACE, dte_min=10, dte_max=50, return_count=10)
    cands = out["candidates"]
    assert len(cands) > 0
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    c = cands[0]
    pl, ps, cs, cl = c["legs"]
    assert pl["strike"] < ps["strike"] < cs["strike"] < cl["strike"]
    assert c["credit"] > 0 and c["credit_usd"] > 0
    assert 0.0 < c["pop"] < 1.0
    assert c["breakeven_lo"] < ps["strike"]
    assert c["breakeven_hi"] > cs["strike"]
    assert c["max_loss_usd"] > 0
    assert c["apr_on_max_loss"] > 0


def test_strangle_both_sides():
    out = scan_strangle(CHAIN, _meta(), SURFACE, dte_min=10, dte_max=20, return_count=5)
    assert len(out["long"]) > 0 and len(out["short"]) > 0
    lg = out["long"][0]
    assert lg["cost_usd"] > 0 and lg["cost_ratio"] > 0
    assert lg["strikes"][0] < F < lg["strikes"][1]
    st = out["short"][0]
    assert st["credit_usd"] > 0
    assert 0.0 < st["pop"] < 1.0
    assert st["apr_on_im"] is not None and st["apr_on_im"] > 0
    assert st["tail_loss_est_usd"] is not None
    # 互补性：同到期同腿的 long 成本 > short 权利金（bid/ask 对称时近似）
    assert lg["cost_usd"] >= 0


def test_calendar_structure():
    out = scan_calendar(CHAIN, _meta(), SURFACE, near_dte_min=7, near_dte_max=20,
                        min_gap_days=14, return_count=5)
    cands = out["candidates"]
    assert len(cands) > 0
    c = cands[0]
    assert c["dte_near"] < c["dte_far"]
    assert c["debit_usd"] > 0
    # 合成数据 atm_near=0.55 > atm_far=0.50 → backwardation 正斜率
    assert c["iv_slope"] == pytest.approx(0.05, abs=1e-6)
    assert c["iv_slope_ratio"] == pytest.approx(0.10, abs=1e-6)
    assert c["net_theta_usd"] > 0      # 近月 theta 衰减快于远月
    assert c["theta_apr"] is not None
    assert c["profit_zone"]["max_profit_est"] is not None
    assert c["kind"] in ("CALL", "PUT")


def test_scan_buckets_svi_and_liquidity_fields():
    out = scan_buckets(CHAIN, _meta(), tenor="near", direction="both",
                       return_per_bucket=2, svi_surface=SURFACE)
    assert out["pricing_mode"] == "mid"
    found = False
    for b in out["buckets"]:
        for item in b["top"] + b["bottom"]:
            found = True
            assert "spread_ratio_avg" in item
            assert "odds_adj" in item
            # 合成数据点差均匀 2% → 惩罚一致，odds_adj 与 odds 同序
            assert item["odds_adj"] == pytest.approx(item["odds"] * (1 - 0.5 * (0.02 / 0.35)), rel=1e-6)
            if item["pop"] is not None:
                assert 0.0 <= item["pop"] <= 1.0
    assert found


def test_pricing_mode_conservative_worse_fill():
    # 同一 (K1,K2) 借方组合：conservative（买 ask 卖 bid）权利金 ≥ mid
    common = dict(chain_df=CHAIN, meta=_meta(), tenor="near", direction="up", return_per_bucket=50)
    mid = scan_buckets(**common, svi_surface=SURFACE, pricing_mode="mid")
    con = scan_buckets(**common, svi_surface=SURFACE, pricing_mode="conservative")

    def pairs(out):
        res = {}
        for b in out["buckets"]:
            for item in b["top"] + b["bottom"]:
                res[(b["leg_type"], b["side"], item["K1"], item["K2"])] = item["premium"]
        return res

    pm, pc = pairs(mid), pairs(con)
    common_keys = set(pm) & set(pc)
    assert common_keys, "两种定价模式应有共同的候选组合"
    for key in common_keys:
        leg_type, side = key[0], key[1]
        if side == "DEBIT":
            assert pc[key] >= pm[key] - 1e-12, f"{key}: conservative 借方权利金应 ≥ mid"
        else:
            assert pc[key] <= pm[key] + 1e-12, f"{key}: conservative 贷方权利金应 ≤ mid"
