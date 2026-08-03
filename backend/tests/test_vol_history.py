"""vol_history 单元测试：幂等追加、固定期限插值、IVP/IVR。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.vol_history import (
    append_rows,
    fixed_tenor_iv,
    ivp_ivr,
    percentile_rank,
)


def test_append_rows_dedupe(tmp_path):
    p = tmp_path / "h.parquet"
    keys = ["date", "base", "expiry_ts"]
    append_rows([
        {"date": "2026-07-25", "base": "BTC", "expiry_ts": 1, "atm_iv": 0.5},
        {"date": "2026-07-25", "base": "BTC", "expiry_ts": 2, "atm_iv": 0.6},
    ], p, keys)
    # 同键覆盖：expiry_ts=1 的 atm_iv 应变 0.55，总行数仍 2
    append_rows([{"date": "2026-07-25", "base": "BTC", "expiry_ts": 1, "atm_iv": 0.55}], p, keys)
    df = pd.read_parquet(p)
    assert len(df) == 2
    row = df[df["expiry_ts"] == 1].iloc[0]
    assert row["atm_iv"] == pytest.approx(0.55)


def _day_slice(dte, atm_iv, quality="ok"):
    return {"date": "2026-07-25", "base": "BTC", "expiry_ts": int(dte),
            "dte": float(dte), "atm_iv": atm_iv, "quality": quality}


def test_fixed_tenor_iv_interpolates():
    df = pd.DataFrame([_day_slice(15, 0.50), _day_slice(45, 0.60)])
    iv30 = fixed_tenor_iv(df, target_dte=30.0)
    # 总方差线性插值：w(30) 应在两个端点之间，iv30 ∈ (0.50, 0.60)
    assert iv30 is not None and 0.50 < iv30 < 0.60
    t1, t2, tt = 15 / 365, 45 / 365, 30 / 365
    w1, w2 = 0.50 ** 2 * t1, 0.60 ** 2 * t2
    expected = float(np.sqrt((w1 + (w2 - w1) * (tt - t1) / (t2 - t1)) / tt))
    assert iv30 == pytest.approx(expected, rel=1e-6)


def test_fixed_tenor_iv_fallback_nearest():
    # 全部切片都在目标一侧：回退到最近切片（dte>=7）
    df = pd.DataFrame([_day_slice(40, 0.55), _day_slice(60, 0.65)])
    assert fixed_tenor_iv(df, target_dte=30.0) == pytest.approx(0.55)
    # 非 ok 切片被剔除后无数据 → None
    df2 = pd.DataFrame([_day_slice(15, 0.5, quality="arb_violation")])
    assert fixed_tenor_iv(df2) is None


def test_ivp_ivr():
    hist = pd.Series(np.arange(1.0, 101.0))  # 1..100
    out = ivp_ivr(hist, current=50.0)
    assert out["days_available"] == 100
    assert out["ivp"] == pytest.approx(0.5)
    assert out["ivr"] == pytest.approx((50 - 1) / (100 - 1))
    # 样本不足
    out2 = ivp_ivr(pd.Series([42.0]), current=43.0)
    assert out2["ivp"] is None and out2["days_available"] == 1


def test_ivr_cold_start_under_30_days_is_none():
    """冷启动期（< IVR_MIN_DAYS）IVR 返回 None，前端显示 "—" 而非误导性 0%。"""
    hist = pd.Series(np.arange(1.0, 21.0))  # 20 天
    out = ivp_ivr(hist, current=10.0)
    assert out["days_available"] == 20
    assert out["ivp"] is not None      # 百分位有样本即可算
    assert out["ivr"] is None          # 窗口不足 → 无统计意义


def test_ivr_flat_series_is_none():
    """无波动范围（vmax == vmin）时 IVR 返回 None，避免除零产出 NaN。"""
    hist = pd.Series(np.full(60, 0.5))  # 天数足够但历史无波动
    out = ivp_ivr(hist, current=0.5)
    assert out["days_available"] == 60
    assert out["ivr"] is None


def test_percentile_rank():
    hist = pd.Series([10.0, 20.0, 30.0, 40.0])
    out = percentile_rank(hist, current=25.0)
    assert out["percentile"] == pytest.approx(0.5)
    assert out["days_available"] == 4
