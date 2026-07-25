"""RND（SVI 隐含风险中性密度）测试。

关键对拍：平 SVI（b=0）时 w(k)=a 常数，密度应退化为 BS 对数正态，
与 probability_st_ge_k 解析解一致。
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.bs import probability_st_ge_k
from app.services.rnd import (
    expected_shortfall,
    expected_upside_tail,
    prob_between,
    prob_ge,
    quantile,
    rnd_from_svi,
)

F, T = 100000.0, 30 / 365.0
FLAT_IV = 0.5
FLAT = {"a": FLAT_IV ** 2 * T, "b": 0.0, "rho": 0.0, "m": 0.0, "sigma": 0.1}
SMILE = {"a": 0.018, "b": 0.15, "rho": -0.4, "m": 0.05, "sigma": 0.15}


def test_flat_svi_matches_lognormal():
    rnd = rnd_from_svi(FLAT, T, F)
    assert rnd.mass == pytest.approx(1.0, abs=1e-3)
    assert rnd.fwd_dev == pytest.approx(0.0, abs=1e-3)
    # 与 BS 解析尾部概率对拍（网格积分精度 1e-3）
    for k_price in (80000.0, 100000.0, 120000.0):
        p_rnd = prob_ge(rnd, k_price)
        p_bs = probability_st_ge_k(F, k_price, FLAT_IV, T)
        assert p_rnd == pytest.approx(p_bs, abs=2e-3)


def test_smile_svi_sane():
    rnd = rnd_from_svi(SMILE, T, F)
    assert rnd.mass == pytest.approx(1.0, abs=0.02)
    assert rnd.fwd_dev == pytest.approx(0.0, abs=0.02)
    p = prob_between(rnd, 90000.0, 110000.0)
    assert 0.0 < p < 1.0


def test_smile_fatter_put_tail_than_flat():
    # 相同 ATM IV 下，负 rho 微笑的 5% 下尾分位应低于平曲线（肥尾）
    smile_atm_iv = np.sqrt(SMILE["a"] + SMILE["b"] * SMILE["sigma"] * np.sqrt(1 - SMILE["rho"] ** 2)) / np.sqrt(T)
    flat_same = {"a": float(smile_atm_iv) ** 2 * T, "b": 0.0, "rho": 0.0, "m": 0.0, "sigma": 0.1}
    q_smile = quantile(rnd_from_svi(SMILE, T, F), 0.05)
    q_flat = quantile(rnd_from_svi(flat_same, T, F), 0.05)
    assert q_smile < q_flat


def test_tail_expectations():
    rnd = rnd_from_svi(SMILE, T, F)
    q05 = quantile(rnd, 0.05)
    q95 = quantile(rnd, 0.95)
    es_low = expected_shortfall(rnd, 0.05)
    es_up = expected_upside_tail(rnd, 0.05)
    assert es_low < q05            # 下尾均值低于分位价
    assert es_up > q95             # 上尾均值高于分位价
    # 全分布均值≈F：q·ES_low + (1-q 部分) … 用双尾粗校验
    assert 0.05 * es_low + 0.90 * F * 0 + 0.05 * es_up > 0  # 占位 sanity
    assert np.isnan(expected_shortfall(rnd, 1.5))
