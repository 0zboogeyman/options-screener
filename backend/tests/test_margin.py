"""Deribit 保证金公式测试（手算样例对照）。"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.margin import (
    im_short_call,
    im_short_put,
    margin_iron_condor,
    margin_strangle_short,
    margin_vertical_credit,
    mm_short_call,
    mm_short_put,
)

S = 100000.0


def test_short_put_im_floor_and_mm():
    # K=90000 put：OTM 10% → max(0.15−0.10, 0.10)+mark = 0.105；
    # MM = max(0.075, 0.075·0.005)+0.005 = 0.08 → IM = max(0.105, 0.08)
    assert im_short_put(S, 90000.0, 0.005) == pytest.approx(0.105)
    # 深 OTM K=50000：OTM 50% → 触下限 0.10+mark
    assert im_short_put(S, 50000.0, 0.001) == pytest.approx(0.101)
    # ITM K=110000：OTM 幅度 0 → 0.15+mark
    assert im_short_put(S, 110000.0, 0.08) == pytest.approx(0.23)


def test_short_call_im():
    assert im_short_call(S, 110000.0, 0.005) == pytest.approx(0.105)
    assert im_short_call(S, 90000.0, 0.02) == pytest.approx(0.17)


def test_mm_put():
    assert mm_short_put(0.005) == pytest.approx(0.075 + 0.005)
    # mark 极大时 max(0.075, 0.075·mark) 取后者
    assert mm_short_put(2.0) == pytest.approx(0.075 * 2.0 + 2.0)


def test_vertical_credit_units():
    # put 价差：short 90000 / long 85000，mark 0.005 / 0.002
    out = margin_vertical_credit(S, 90000.0, 85000.0, 0.005, 0.002, "PUT")
    assert out["credit"] == pytest.approx(0.003)
    assert out["credit_usd"] == pytest.approx(300.0)
    assert out["max_loss_usd"] == pytest.approx(5000.0 - 300.0)
    assert out["im_standard"] == pytest.approx(0.105)  # 同裸卖 90000 put
    assert out["roi_on_max_loss"] == pytest.approx(300.0 / 4700.0)
    assert out["estimate"] is True


def test_iron_condor_one_side_loss():
    # put 90k/85k（mark .005/.002），call 110k/115k（mark .006/.003）
    out = margin_iron_condor(S, 85000.0, 90000.0, 110000.0, 115000.0,
                             0.005, 0.002, 0.006, 0.003)
    assert out["credit"] == pytest.approx(0.006)
    assert out["credit_usd"] == pytest.approx(600.0)
    # 两翼同宽 5000 → max_loss = 5000 − 600
    assert out["max_loss_usd"] == pytest.approx(4400.0)
    # im_standard = put 腿 IM(0.105) + call 腿 IM(max(0.15−0.1,0.1)+0.006=0.106)
    assert out["im_standard"] == pytest.approx(0.105 + 0.106)


def test_strangle_short_no_max_loss():
    out = margin_strangle_short(S, 90000.0, 110000.0, 0.005, 0.005)
    assert out["max_loss_usd"] is None
    assert out["credit"] == pytest.approx(0.010)
    assert out["im_standard"] == pytest.approx(0.105 + 0.105)
    assert out["roi_on_im"] == pytest.approx(0.010 / 0.21)


def test_negative_mark_returns_nan():
    """负权利金（异常报价）时保证金返回 NaN，避免产出无意义数值污染下游。"""
    assert np.isnan(im_short_call(S, 110000.0, -0.005))
    assert np.isnan(im_short_put(S, 90000.0, -0.005))
    assert np.isnan(mm_short_call(-1.0))
    assert np.isnan(mm_short_put(-1.0))
