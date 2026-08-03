from __future__ import annotations

import numpy as np
import pandas as pd

# 打标阈值：买卖价差超过中间价 15% 标记为 wide_spread（quality flag）。
# 注意与 scanner 中的过滤阈值 SPREAD_RATIO_MAX=0.35 语义不同：
# 0.15 用于给单腿"贴标签"，0.35 用于在扫描时"剔除不可用腿"。
WIDE_SPREAD_THRESHOLD = 0.15

_REQUIRED_COLS = [
    "date", "base", "instrument", "expiry_ts", "strike", "option_type",
    "bid", "ask", "mark_price", "mark_iv", "underlying", "oi", "asof_ts",
]


def prep_chain(df: pd.DataFrame) -> pd.DataFrame:
    """为期权链补充 mid / quality_flag / spread_ratio 三列（向量化实现）。

    不修改传入的 df（先 copy），保证调用方可安全复用缓存的原始链。
    价格优先级：bid/ask 中间价 > mark_price > 单边报价。
    """
    df = df.copy()
    for c in _REQUIRED_COLS:
        if c not in df.columns:
            df[c] = np.nan

    # mark_iv 单位兜底：ETL 自 2026-07-22 起已归一为小数；更早落盘的数据是
    # Deribit 原始百分数形式（如 42.5）。启发式：>5 视为百分数并转换
    # （真实小数波动率不可能超过 500%）。
    iv_raw = pd.to_numeric(df["mark_iv"], errors="coerce")
    df["mark_iv"] = np.where(iv_raw > 5.0, iv_raw / 100.0, iv_raw)

    bid = pd.to_numeric(df["bid"], errors="coerce").to_numpy(dtype=float)
    ask = pd.to_numeric(df["ask"], errors="coerce").to_numpy(dtype=float)
    mark = pd.to_numeric(df["mark_price"], errors="coerce").to_numpy(dtype=float)

    has_ba = ~np.isnan(bid) & ~np.isnan(ask)
    has_mark = ~np.isnan(mark)
    has_bid = ~np.isnan(bid)
    has_ask = ~np.isnan(ask)

    mid = np.where(
        has_ba, 0.5 * (bid + ask),
        np.where(has_mark, mark,
                 np.where(has_bid, bid,
                          np.where(has_ask, ask, np.nan))),
    )

    # spread_ratio 仅在双边报价为正且 mid 有效时有意义，否则 inf（过滤时必被剔除）
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (ask - bid) / mid
    valid_ratio = has_ba & (bid > 0) & (ask > 0) & (mid > 0)
    spread_ratio = np.where(valid_ratio, ratio, np.inf)

    # quality_flag: missing（缺价）> invalid（倒挂）> wide_spread（过宽）> ok
    with np.errstate(divide="ignore", invalid="ignore"):
        width_ratio = (ask - bid) / mid
    missing = ~(has_ba & ~np.isnan(mid) & (mid > 0))
    invalid = ~missing & (ask < bid)
    wide = ~missing & ~invalid & (width_ratio > WIDE_SPREAD_THRESHOLD)
    quality_flag = np.where(
        missing, "missing",
        np.where(invalid, "invalid",
                 np.where(wide, "wide_spread", "ok")),
    )

    df["mid"] = mid
    df["quality_flag"] = quality_flag
    df["spread_ratio"] = spread_ratio
    return df
