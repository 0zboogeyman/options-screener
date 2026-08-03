"""边缘 case 测试：零 bid/ask、极高 IV、SVI 拟合失败回退、RND 极端参数。

覆盖的是生产数据中真实会遇到的情形：深虚值合约无报价、极端行情 IV 爆表、
切片报价不足/质量差时拟合必须优雅回退，绝不能抛异常或产出 NaN 毒化下游。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.bs import (
    delta_call_vec,
    price_call_vec,
    price_put_vec,
    strike_from_delta,
    theta_vec,
    vega_vec,
)
from app.services.preprocessing import prep_chain
from app.services.rnd import prob_between, rnd_from_svi
from app.services.svi import fit_svi_slice


def _chain_row(bid, ask, mark_price=0.01, mark_iv=0.5):
    return {
        "date": "2026-07-26", "base": "BTC", "instrument": "BTC-28AUG26-60000-P",
        "expiry_ts": 1787904000000, "strike": 60000.0, "option_type": "P",
        "bid": bid, "ask": ask, "mark_price": mark_price, "mark_iv": mark_iv,
        "underlying": 64000.0, "oi": 100, "asof_ts": 1784908800000,
    }


# ---------------------------------------------------------------------------
# 零 bid/ask
# ---------------------------------------------------------------------------

class TestZeroBidAsk:
    def test_zero_both_sides_spread_ratio_inf(self):
        df = prep_chain(pd.DataFrame([_chain_row(bid=0.0, ask=0.0)]))
        # 双边为零（非缺失）：mid=0、quality=missing、ratio=inf。
        # 下游 scanner 的 mid.notna() 会放行它，靠 spread_ratio<=MAX 兜底剔除。
        assert np.isinf(df["spread_ratio"].iloc[0])
        assert df["mid"].iloc[0] == 0.0
        assert df["quality_flag"].iloc[0] == "missing"

    def test_nan_both_sides_falls_back_to_mark(self):
        df = prep_chain(pd.DataFrame([_chain_row(bid=None, ask=None)]))
        assert df["mid"].iloc[0] == 0.01
        assert np.isinf(df["spread_ratio"].iloc[0])

    def test_one_sided_quote_uses_that_side(self):
        # 单边报价 + 无 mark_price 时才回退单边（优先级：双边中点 > mark > 单边）
        df = prep_chain(pd.DataFrame([_chain_row(bid=0.005, ask=None, mark_price=None)]))
        assert df["mid"].iloc[0] == 0.005
        df2 = prep_chain(pd.DataFrame([_chain_row(bid=None, ask=0.006, mark_price=None)]))
        assert df2["mid"].iloc[0] == 0.006
        # 有 mark_price 时优先 mark（单边报价仅作最后兜底）
        df3 = prep_chain(pd.DataFrame([_chain_row(bid=0.005, ask=None, mark_price=0.01)]))
        assert df3["mid"].iloc[0] == 0.01

    def test_all_missing_gives_nan_mid_and_missing_flag(self):
        df = prep_chain(pd.DataFrame([_chain_row(bid=None, ask=None, mark_price=None)]))
        assert np.isnan(df["mid"].iloc[0])
        assert df["quality_flag"].iloc[0] == "missing"

    def test_inverted_market_flagged_invalid(self):
        df = prep_chain(pd.DataFrame([_chain_row(bid=0.008, ask=0.005)]))
        assert df["quality_flag"].iloc[0] == "invalid"


# ---------------------------------------------------------------------------
# 极高 IV（>200%，极端行情真实出现）
# ---------------------------------------------------------------------------

class TestExtremeIV:
    def test_delta_bounded_at_250pct_iv(self):
        d = delta_call_vec(64000.0, np.array([50000.0, 64000.0, 80000.0]), 2.5, 30 / 365)
        assert np.all(np.isfinite(d))
        assert np.all((d >= 0) & (d <= 1))

    def test_price_finite_and_bounded_at_300pct_iv(self):
        c = price_call_vec(64000.0, 64000.0, 3.0, 30 / 365)
        assert np.isfinite(c)
        assert 0 < c < 64000.0  # call 价格不超标的
        p = price_put_vec(64000.0, 64000.0, 3.0, 30 / 365)
        assert np.isfinite(p)
        assert 0 < p < 64000.0

    def test_greeks_finite_at_200pct_iv(self):
        v = vega_vec(64000.0, 64000.0, 2.0, 30 / 365)
        th = theta_vec(64000.0, 64000.0, 2.0, 30 / 365)
        assert np.isfinite(v) and v > 0
        assert np.isfinite(th)

    def test_strike_from_delta_roundtrip_at_high_iv(self):
        k = strike_from_delta(64000.0, 0.25, 2.0, 60 / 365, kind="call")
        assert np.isfinite(k) and k > 0
        # 往返：由 delta 反解的行权价再算 delta 应回到 0.25
        d_back = delta_call_vec(64000.0, k, 2.0, 60 / 365)
        assert abs(float(d_back) - 0.25) < 1e-6

    def test_zero_and_tiny_time_inputs_no_crash(self):
        # t=0 / 负 t：非法输入返回 NaN 而不是抛异常
        c = price_call_vec(64000.0, 64000.0, 0.5, 0.0)
        assert np.isnan(c)


# ---------------------------------------------------------------------------
# SVI 拟合失败回退（quality != ok，参数字段为 None，绝不抛异常）
# ---------------------------------------------------------------------------

class TestSviFallback:
    def test_too_few_quotes_returns_insufficient(self):
        strikes = np.array([60000.0, 62000.0, 64000.0])  # 3 < MIN_QUOTES=5
        ivs = np.array([0.4, 0.38, 0.36])
        fit = fit_svi_slice(strikes, ivs, np.ones(3), forward=64000.0, t_years=30 / 365)
        assert fit["quality"] == "insufficient"
        assert fit["a"] is None

    def test_all_nan_iv_no_crash(self):
        strikes = np.linspace(50000, 80000, 10)
        ivs = np.full(10, np.nan)
        fit = fit_svi_slice(strikes, ivs, np.ones(10), forward=64000.0, t_years=30 / 365)
        assert fit["quality"] != "ok"
        assert fit["a"] is None

    def test_negative_and_zero_iv_filtered(self):
        strikes = np.linspace(50000, 80000, 10)
        ivs = np.array([-0.1, 0.0, 0.4, 0.38, 0.36, 0.35, 0.34, 0.33, 0.35, 0.37])
        fit = fit_svi_slice(strikes, ivs, np.ones(10), forward=64000.0, t_years=30 / 365)
        # 负值/零被过滤后剩 8 个有效点，应正常拟合不抛异常
        assert fit["quality"] in ("ok", "fit_failed", "arb_violation")
        assert fit["n_quotes"] == 8

    def test_iv_above_300pct_filtered(self):
        strikes = np.linspace(50000, 80000, 10)
        ivs = np.full(10, 5.0)  # 500% 超出有效区间（<3.0）
        fit = fit_svi_slice(strikes, ivs, np.ones(10), forward=64000.0, t_years=30 / 365)
        assert fit["quality"] != "ok"

    def test_constant_iv_flat_smile(self):
        # 常数 IV（平微笑）：合法市场形态，应拟合成功或优雅失败，不抛异常
        strikes = np.linspace(50000, 80000, 15)
        ivs = np.full(15, 0.5)
        fit = fit_svi_slice(strikes, ivs, np.ones(15) * 100, forward=64000.0, t_years=30 / 365)
        assert fit["quality"] in ("ok", "fit_failed", "arb_violation")
        if fit["quality"] == "ok":
            assert abs(fit["atm_iv"] - 0.5) < 0.05

    def test_zero_forward_no_crash(self):
        # forward=0 时 k=ln(K/1e-9) 全部退化到极右尾：函数数值稳定不抛异常，
        # 结果无经济意义但绝不产 NaN 毒化下游（ETL 上游已保证 underlying 非零）
        strikes = np.linspace(50000, 80000, 10)
        ivs = np.full(10, 0.4)
        fit = fit_svi_slice(strikes, ivs, np.ones(10), forward=0.0, t_years=30 / 365)
        assert fit["quality"] in ("ok", "fit_failed", "arb_violation", "insufficient")


# ---------------------------------------------------------------------------
# RND 极端参数（自检 mass/fwd_dev，毒化参数不产 NaN）
# ---------------------------------------------------------------------------

class TestRndExtreme:
    def test_flat_svi_extreme_short_tenor(self):
        # 平 SVI（b≈0）+ 极短期限：对数正态极限，mass 必须 ≈1
        params = dict(a=0.001, b=1e-6, rho=0.0, m=0.0, sigma=0.1, atm_iv=0.5)
        rnd = rnd_from_svi(params, t_years=2 / 365, forward=64000.0)
        assert abs(rnd.mass - 1.0) < 0.01
        assert abs(rnd.fwd_dev) < 0.005

    def test_deep_skew_rho_no_nan(self):
        # 深度负偏（crypto 恐慌形态）：密度非负、概率在 [0,1]
        params = dict(a=0.03, b=0.2, rho=-0.9, m=0.05, sigma=0.25, atm_iv=0.6)
        rnd = rnd_from_svi(params, t_years=30 / 365, forward=64000.0)
        assert np.all(rnd.pdf >= 0)
        p = prob_between(rnd, 50000.0, 80000.0)
        assert np.isfinite(p) and 0.0 <= p <= 1.0

    def test_tiny_sigma_no_crash(self):
        params = dict(a=0.01, b=0.05, rho=-0.3, m=0.0, sigma=1e-4, atm_iv=0.4)
        rnd = rnd_from_svi(params, t_years=30 / 365, forward=64000.0)
        assert np.all(np.isfinite(rnd.pdf))


# ---------------------------------------------------------------------------
# loader 数据层校验（base 白名单 / 非法日期目录过滤）
# ---------------------------------------------------------------------------

class TestLoaderValidation:
    def test_load_chain_rejects_invalid_base(self):
        """非 BTC/ETH 的 base 在校验阶段即抛 ValueError，不触发磁盘 IO。"""
        from app.services import loader

        with pytest.raises(ValueError):
            loader.load_chain_for(date="2026-07-26", base="XRP")

    def test_list_available_dates_filters_invalid(self, monkeypatch, tmp_path):
        """非法格式目录名（非 YYYY-MM-DD 前缀）不应污染可用日期列表。"""
        from app.services import loader

        monkeypatch.setattr(loader, "DATA_ROOT", tmp_path)
        (tmp_path / "dt=2026-07-26-08").mkdir()
        (tmp_path / "dt=2026-07-25-06").mkdir()
        (tmp_path / "dt=garbage").mkdir()
        dates = loader.list_available_dates()
        assert dates == ["2026-07-25", "2026-07-26"]
