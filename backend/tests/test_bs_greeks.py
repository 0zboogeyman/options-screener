"""bs.py 扩展（vega/theta/gamma/prob_between/strike_from_delta）测试。"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.bs import (
    delta_call_vec,
    gamma_vec,
    prob_between,
    probability_st_ge_k,
    strike_from_delta,
    strike_from_delta_vec,
    theta_vec,
    vega_vec,
)

S, VOL, T = 100000.0, 0.5, 30 / 365.0
K = np.array([80000.0, 100000.0, 120000.0])


def test_vega_gamma_identity():
    # vega = gamma · S² · σ · t（解析恒等式）
    v = vega_vec(S, K, VOL, T)
    g = gamma_vec(S, K, VOL, T)
    assert np.allclose(v, g * S * S * VOL * T, rtol=1e-10)


def test_theta_vega_identity():
    # theta（每年）= −vega · σ / (2t)
    v = vega_vec(S, K, VOL, T)
    th = theta_vec(S, K, VOL, T)
    assert np.allclose(th * 365.0, -v * VOL / (2.0 * T), rtol=1e-10)
    assert np.all(th < 0)  # r=0 时间衰减恒为负


def test_gamma_vs_finite_difference_delta():
    eps = S * 1e-4
    d_up = delta_call_vec(S + eps, K, VOL, T)
    d_dn = delta_call_vec(S - eps, K, VOL, T)
    g_fd = (d_up - d_dn) / (2 * eps)
    assert np.allclose(gamma_vec(S, K, VOL, T), g_fd, rtol=1e-4)


def test_prob_between_matches_tail_diff():
    lo, hi = 90000.0, 110000.0
    p = prob_between(S, lo, hi, VOL, T)
    expect = probability_st_ge_k(S, lo, VOL, T) - probability_st_ge_k(S, hi, VOL, T)
    assert p == pytest.approx(expect)
    assert 0.0 < p < 1.0
    # 超宽区间 → 接近 1；非法输入 → nan
    assert prob_between(S, 1.0, 1e9, VOL, T) == pytest.approx(1.0, abs=1e-6)
    assert np.isnan(prob_between(S, hi, lo, VOL, T))


def test_strike_from_delta_roundtrip():
    for d in (0.10, 0.25, 0.50):
        k = strike_from_delta(S, d, VOL, T, kind="call")
        assert delta_call_vec(S, k, VOL, T) == pytest.approx(d, abs=1e-9)
        k_put = strike_from_delta(S, -d, VOL, T, kind="put")
        assert delta_call_vec(S, k_put, VOL, T) - 1.0 == pytest.approx(-d, abs=1e-9)
    # 非法 delta
    assert np.isnan(strike_from_delta(S, 1.5, VOL, T))
    assert np.isnan(strike_from_delta(S, 0.5, VOL, T, kind="put"))


def test_bad_inputs_nan():
    assert np.all(np.isnan(vega_vec(S, K, -1.0, T)))
    assert np.all(np.isnan(gamma_vec(S, K, VOL, 0.0)))
    assert np.all(np.isnan(strike_from_delta_vec(S, np.array([-0.1, 1.1]), VOL, T)))
