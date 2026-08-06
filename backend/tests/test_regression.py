"""第六轮改进回归测试：数值锁定本轮修复行为。

覆盖：
  #1   --date 零填充/日历校验（etl_daily._validate_date）
  #2   odds 双语义 + USD 净值口径（scanner._calc_vertical_metrics）
  #3   k_lo/k_hi 归一化（行权价传参顺序无关）
  #7   BS 尾部概率直接 N(−d₂)，深虚值不归零（bs.probability_st_le_k）
  #9/#14  锚定区间评分管道（scoring.apply_scores / MIN_SCORE）
  #16  RND 动态网格（高波动切片尾部不截断）
  #22  跨字段 422（多腿请求模型成对 min/max 校验）
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from app.services import scanner
from app.services.bs import probability_st_ge_k, probability_st_le_k
from app.services.rnd import expected_shortfall, rnd_from_svi
from app.services.scoring import MIN_SCORE, apply_scores
from scripts.etl_daily import _validate_date

S = 100000.0
T = 30 / 365.0
IV = 0.5


# ---------------------------------------------------------------------------
# #1 --date 校验
# ---------------------------------------------------------------------------


class TestValidateDate:
    def test_accepts_canonical(self):
        assert _validate_date("2026-08-06") == "2026-08-06"

    @pytest.mark.parametrize("bad", ["2026-8-6", "2026-08-6", "2026-8-06", "20260806", "2026-08"])
    def test_rejects_non_zero_padded(self, bad):
        with pytest.raises(ValueError):
            _validate_date(bad)

    @pytest.mark.parametrize("bad", ["2026-02-30", "2026-13-01", "2026-00-10"])
    def test_rejects_invalid_calendar(self, bad):
        with pytest.raises(ValueError):
            _validate_date(bad)


# ---------------------------------------------------------------------------
# #2/#3 垂直价差指标：odds 双语义 + USD 净值 + 顺序无关
# ---------------------------------------------------------------------------


class TestVerticalMetrics:
    def test_debit_odds_and_usd_net(self):
        m = scanner._calc_vertical_metrics(
            "CALL", "DEBIT", 100000.0, 110000.0,
            long_px=0.08, short_px=0.05, s=S, iv=IV, t_years=T,
        )
        premium_usd = m["premium"] * S
        assert premium_usd == pytest.approx(3000.0, rel=1e-9)
        assert m["max_loss"] == pytest.approx(premium_usd, rel=1e-9)          # 净支出
        assert m["max_profit"] == pytest.approx(10000.0 - premium_usd, rel=1e-9)  # 宽度−净支出
        # 审计 A-1：odds = max_profit/max_loss = (width−P)/P（真实 reward/risk）
        assert m["odds"] == pytest.approx((10000.0 - premium_usd) / premium_usd, rel=1e-9)

    def test_credit_odds_and_usd_net(self):
        m = scanner._calc_vertical_metrics(
            "CALL", "CREDIT", 100000.0, 110000.0,
            long_px=0.03, short_px=0.08, s=S, iv=IV, t_years=T,
        )
        premium_usd = m["premium"] * S
        assert premium_usd == pytest.approx(5000.0, rel=1e-9)
        assert m["max_profit"] == pytest.approx(premium_usd, rel=1e-9)        # 净收入
        assert m["max_loss"] == pytest.approx(10000.0 - premium_usd, rel=1e-9)   # 宽度−净收入
        # 审计 A-1：odds = max_profit/max_loss = P/(width−P)
        assert m["odds"] == pytest.approx(premium_usd / (10000.0 - premium_usd), rel=1e-9)

    def test_credit_max_loss_clamped_non_negative(self):
        """审计 A-3：CREDIT 净值亏损钳制 ≥0，避免 credit>width 时负 max_loss。"""
        m = scanner._calc_vertical_metrics(
            "CALL", "CREDIT", 100000.0, 110000.0,
            long_px=0.02, short_px=0.12, s=S, iv=IV, t_years=T,  # credit=0.10 → 10000=width
        )
        assert m["max_loss"] == 0.0
        assert m["odds"] == float("inf")

    def test_k_order_invariant(self):
        """行权价传参顺序无关：低K/高K 任意顺序结果一致（k_lo/k_hi 归一化）。"""
        a = scanner._calc_vertical_metrics(
            "PUT", "CREDIT", 100000.0, 90000.0,
            long_px=0.02, short_px=0.06, s=S, iv=IV, t_years=T,
        )
        b = scanner._calc_vertical_metrics(
            "PUT", "CREDIT", 90000.0, 100000.0,
            long_px=0.02, short_px=0.06, s=S, iv=IV, t_years=T,
        )
        assert a["max_profit"] == pytest.approx(b["max_profit"], rel=1e-12)
        assert a["max_loss"] == pytest.approx(b["max_loss"], rel=1e-12)
        assert a["odds"] == pytest.approx(b["odds"], rel=1e-12)
        assert a["pop"] == pytest.approx(b["pop"], rel=1e-12)


# ---------------------------------------------------------------------------
# #7 BS 尾部概率：深虚值不归零
# ---------------------------------------------------------------------------


class TestMarginNanGuard:
    """审计 A-2：margin 模块显式 isfinite 校验，NaN 输入不再产出假数值。"""

    def test_im_short_call_nan_returns_nan(self):
        from app.services import margin

        assert math.isnan(margin.im_short_call(float("nan"), 100000.0, 0.02))
        assert math.isnan(margin.im_short_call(100000.0, 100000.0, float("nan")))
        # 正常输入不受影响：ATM 裸卖 IM = max(0.15−0, 0.10) + 0.02 = 0.17
        assert margin.im_short_call(100000.0, 100000.0, 0.02) == pytest.approx(0.17)

    def test_vertical_credit_nan_propagates(self):
        from app.services import margin

        res = margin.margin_vertical_credit(
            float("nan"), 100000.0, 90000.0, 0.06, 0.02, "PUT",
        )
        assert math.isnan(res["max_loss_usd"])
        # 正常输入数值不变（回归）
        ok = margin.margin_vertical_credit(
            100000.0, 100000.0, 90000.0, 0.06, 0.02, "PUT",
        )
        assert ok["max_loss_usd"] == pytest.approx(10000.0 - 4000.0, rel=1e-9)


class TestBsTailProbability:
    def test_deep_otm_le_k_not_zero(self):
        """深虚值（d₂≈7）下 1−N(d₂) 会灾难性抵消为 0，N(−d₂) 保持非零。"""
        s, k, vol, t = 100000.0, 50000.0, 0.3, 0.1
        p = probability_st_le_k(s, k, vol, t)
        assert 0.0 < p < 1e-10
        # 对拍解析式 N(−d₂) = 0.5·erfc(d₂/√2)
        vt = vol * math.sqrt(t)
        d2 = (math.log(s / k) - 0.5 * vol * vol * t) / vt
        assert p == pytest.approx(0.5 * math.erfc(d2 / math.sqrt(2.0)), rel=1e-9)

    def test_complementarity(self):
        """浅虚值处 P(S_T≤K) 与 P(S_T≥K) 互补。"""
        p_le = probability_st_le_k(S, 95000.0, IV, T)
        p_ge = probability_st_ge_k(S, 95000.0, IV, T)
        assert p_le + p_ge == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# #9/#14 评分管道
# ---------------------------------------------------------------------------


class TestScoring:
    def test_apply_scores_sorts_and_filters(self):
        from app.services.single_leg import CSP_SCORE_WEIGHTS

        cands = [
            {"apr": 0.5, "discount_pct": 0.3, "assign_prob": 0.1, "liquidity_score": 4.0},
            {"apr": 0.25, "discount_pct": 0.15, "assign_prob": 0.4, "liquidity_score": 2.5},
        ]
        apply_scores(cands, CSP_SCORE_WEIGHTS)
        assert len(cands) == 1
        assert cands[0]["score"] == pytest.approx(66.5, abs=0.2)  # 锚定区间数值锁定
        assert cands[0]["score"] >= MIN_SCORE

    def test_low_score_candidates_filtered(self):
        from app.services.single_leg import CSP_SCORE_WEIGHTS

        weak = [{"apr": 0.01, "discount_pct": 0.001, "assign_prob": 0.9, "liquidity_score": 0.1}]
        apply_scores(weak, CSP_SCORE_WEIGHTS)
        assert weak == []

    def test_ivp_score_defaults_neutral(self):
        from app.services.multi_leg import IC_SCORE_WEIGHTS

        cands = [
            {"apr_on_max_loss": 0.5, "pop": 0.6, "liquidity_score": 4.0},  # 无 ivp_score
        ]
        apply_scores(cands, IC_SCORE_WEIGHTS)
        assert cands  # 缺省按 0.5 入分，不因缺字段被滤掉或崩溃
        assert 0.0 <= cands[0]["score"] <= 100.0


# ---------------------------------------------------------------------------
# #16 RND 动态网格
# ---------------------------------------------------------------------------


class TestRndDynamicGrid:
    def test_high_vol_expands_grid(self):
        # 高波动 + 长期限：w_atm 大 → 网格半宽 > 3（固定 ±3 会截断尾部）
        params = dict(a=0.3, b=0.2, rho=-0.3, m=0.0, sigma=0.5)
        rnd = rnd_from_svi(params, t_years=180 / 365, forward=S)
        half = max(abs(rnd.k[0]), abs(rnd.k[-1]))
        assert half > 3.0
        # 动态网格捕获更深的尾部：5% ES 价位低于固定 ±3 网格的结果
        rnd_fixed = rnd_from_svi(params, t_years=180 / 365, forward=S, k_range=(-3.0, 3.0))
        assert expected_shortfall(rnd, 0.05) < expected_shortfall(rnd_fixed, 0.05)

    def test_low_vol_keeps_min_grid(self):
        low = dict(a=0.02, b=0.01, rho=0.0, m=0.0, sigma=0.1)
        rnd = rnd_from_svi(low, t_years=7 / 365, forward=S)
        assert max(abs(rnd.k[0]), abs(rnd.k[-1])) == pytest.approx(3.0)

    def test_flat_svi_still_matches_lognormal(self):
        # 动态网格下平 SVI 仍与 BS 解析解对拍（回归不破坏原精度）
        from app.services.bs import probability_st_ge_k

        flat = {"a": IV ** 2 * T, "b": 0.0, "rho": 0.0, "m": 0.0, "sigma": 0.1}
        rnd = rnd_from_svi(flat, T, S)
        for k_price in (80000.0, 100000.0, 120000.0):
            p_rnd = 1.0 - np.interp(math.log(k_price / S), rnd.k, rnd.cdf)
            p_bs = probability_st_ge_k(S, k_price, IV, T)
            assert p_rnd == pytest.approx(p_bs, abs=2e-3)


# ---------------------------------------------------------------------------
# #22 跨字段 min/max 422
# ---------------------------------------------------------------------------


class TestCrossFieldValidation:
    def test_inverted_min_max_rejected(self):
        from app.api.routes_multi_leg import CalendarRequest, IronCondorRequest, StrangleRequest

        with pytest.raises(ValidationError):
            IronCondorRequest(base="BTC", dte_min=60, dte_max=14)
        with pytest.raises(ValidationError):
            IronCondorRequest(base="BTC", short_delta_min=0.3, short_delta_max=0.1)
        with pytest.raises(ValidationError):
            StrangleRequest(base="ETH", delta_min=0.4, delta_max=0.2)
        with pytest.raises(ValidationError):
            CalendarRequest(base="BTC", near_dte_min=30, near_dte_max=7)

    def test_valid_defaults_accepted(self):
        from app.api.routes_multi_leg import CalendarRequest, IronCondorRequest, StrangleRequest

        IronCondorRequest(base="BTC")
        StrangleRequest(base="ETH")
        CalendarRequest(base="BTC")
