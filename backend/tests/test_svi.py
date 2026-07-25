"""SVI 拟合单元测试：合成微笑参数恢复、质量标记、无套利校验。"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.services.svi import (
    _check_no_arbitrage,
    _min_total_variance,
    butterfly_g,
    fit_svi_slice,
    raw_svi_w,
    svi_iv,
)

F = 100000.0
T = 30 / 365.0
TRUE = dict(a=0.02, b=0.15, rho=-0.4, m=0.05, sigma=0.15)


def _synthetic_chain(noise: float = 0.0, n: int = 25, seed: int = 7):
    rng = np.random.default_rng(seed)
    strikes = np.linspace(0.7 * F, 1.35 * F, n)
    k = np.log(strikes / F)
    w = raw_svi_w(k, TRUE["a"], TRUE["b"], TRUE["rho"], TRUE["m"], TRUE["sigma"])
    ivs = np.sqrt(w / T)
    if noise > 0:
        ivs = ivs * (1.0 + rng.normal(0, noise, size=n))
    ois = rng.integers(50, 500, size=n).astype(float)
    return strikes, ivs, ois


def test_fit_recovers_synthetic_smile():
    strikes, ivs, ois = _synthetic_chain(noise=0.005)
    fit = fit_svi_slice(strikes, ivs, ois, forward=F, t_years=T)

    assert fit["quality"] == "ok"
    assert fit["n_quotes"] == len(strikes)

    # ATM IV 应接近真值（k=0 处）
    true_atm = math.sqrt(raw_svi_w(np.array([0.0]), TRUE["a"], TRUE["b"],
                                   TRUE["rho"], TRUE["m"], TRUE["sigma"])[0] / T)
    assert fit["atm_iv"] == pytest.approx(true_atm, abs=0.01)

    # rho < 0 → put 翼 IV 高于 call 翼 → rr25 < 0
    assert fit["rr25"] is not None and fit["rr25"] < 0
    # butterfly 应为正（两翼 IV 高于 ATM）
    assert fit["bf25"] is not None and fit["bf25"] > 0
    assert fit["rmse_iv"] < 0.01


def test_insufficient_quotes():
    strikes = np.array([0.9 * F, F, 1.1 * F])
    ivs = np.array([0.5, 0.45, 0.48])
    fit = fit_svi_slice(strikes, ivs, np.array([10.0, 10.0, 10.0]), forward=F, t_years=T)
    assert fit["quality"] == "insufficient"
    assert fit["a"] is None


def test_invalid_iv_filtered_out():
    strikes, ivs, ois = _synthetic_chain(n=10)
    ivs[:] = np.nan
    fit = fit_svi_slice(strikes, ivs, ois, forward=F, t_years=T)
    assert fit["quality"] == "insufficient"


def test_no_arbitrage_check():
    # 正常参数：无套利
    good = dict(a=0.02, b=0.15, rho=-0.4, m=0.05, sigma=0.15)
    assert _check_no_arbitrage(good)
    # a 使总方差最小值为负：违规
    bad = dict(a=-0.5, b=0.1, rho=0.0, m=0.0, sigma=0.1)
    assert _min_total_variance(bad["a"], bad["b"], bad["rho"], bad["sigma"]) < 0
    assert not _check_no_arbitrage(bad)


def test_svi_iv_monotone_wings():
    # rho<0 的曲线：深度 OTM put（k<0）IV 应高于同距离 OTM call（k>0）
    k = np.array([-0.3, 0.0, 0.3])
    iv = svi_iv(k, TRUE, T)
    assert iv[0] > iv[2]
    assert iv[1] == pytest.approx(math.sqrt(raw_svi_w(np.array([0.0]), **TRUE)[0] / T))
