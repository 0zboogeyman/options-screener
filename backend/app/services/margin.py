"""Deribit 保证金估算（标准账户，逆向期权）。

官方公式（Deribit 知识库 · Standard Margin，币种单位）：
  裸卖 Call IM = max(0.15 − max((K−S)/S, 0), 0.10) + mark
  裸卖 Put  IM = max(max(0.15 − max(S−K, 0)/S, 0.10) + mark, MM_put)
  裸卖 Call MM = 0.075 + mark
  裸卖 Put  MM = max(0.075, 0.075·mark) + mark
  买方只付权利金，无 IM。

单位约定（重要）：
  * 单腿 IM/MM 函数用【币种】（与 Deribit 一致，mark 也是币种报价）；
  * 组合级函数统一输出【双单位】：credit/im_standard 给币种与 USD 两个字段，
    USD 按当前 S 换算（逆向期权到期损益以币结算，按即期换算是近似，
    忽略凸性，故全部标注 estimate）；
  * max_loss 用 USD 口径（翼宽 USD − 权利金 USD），评分建议用该口径的 ROI；
  * im_standard 按官方公式逐腿求和（标准账户对价差/组合无减免；
    PM 组合保证金账户会显著更低）。
"""
from __future__ import annotations

import math
from typing import Dict, Optional

# 官方公式系数（Deribit 调整时改这里）
IM_LEVEL = 0.15          # OTM 裸卖基础保证金率
IM_FLOOR = 0.10          # OTM 裸卖保证金率下限
MM_LEVEL = 0.075         # 维持保证金率


def _finite(*values: float) -> bool:
    """全部参数均为有限浮点。审计 A-2：显式 isfinite 校验，避免 Python
    max(nan, x) 隐式返回 x 而把 NaN 静默"修成"有效数字。"""
    return all(math.isfinite(v) for v in values)


def mm_short_call(mark: float) -> float:
    """裸卖 Call 维持保证金（币种）。"""
    if not _finite(mark) or mark < 0:
        return float("nan")
    return MM_LEVEL + mark


def mm_short_put(mark: float) -> float:
    """裸卖 Put 维持保证金（币种）。"""
    if not _finite(mark) or mark < 0:
        return float("nan")
    return max(MM_LEVEL, MM_LEVEL * mark) + mark


def im_short_call(s: float, k: float, mark: float) -> float:
    """裸卖 Call 初始保证金（币种）：max(0.15 − OTM 幅度, 0.10) + mark。"""
    if not _finite(s, k, mark) or s <= 0 or k <= 0 or mark < 0:
        return float("nan")
    otm_pct = max((k - s) / s, 0.0)
    return max(IM_LEVEL - otm_pct, IM_FLOOR) + mark


def im_short_put(s: float, k: float, mark: float) -> float:
    """裸卖 Put 初始保证金（币种）：max(同 Call 结构, MM_put)。"""
    if not _finite(s, k, mark) or s <= 0 or k <= 0 or mark < 0:
        return float("nan")
    otm_pct = max((s - k) / s, 0.0)
    im = max(IM_LEVEL - otm_pct, IM_FLOOR) + mark
    return max(im, mm_short_put(mark))


def _usd(coin: Optional[float], s: float) -> Optional[float]:
    return None if coin is None else coin * s


def margin_vertical_credit(
    s: float, short_k: float, long_k: float,
    short_mark: float, long_mark: float, kind: str,
) -> Dict:
    """贷方垂直价差（short short_k / long long_k，收权利金）。

    credit(币种) = short_mark − long_mark；max_loss(USD) = 宽度 − credit·S。
    im_standard 按裸卖 short 腿官方公式（买腿无 IM，标准账户无价差减免）。
    """
    width_usd = abs(short_k - long_k)
    credit = short_mark - long_mark
    credit_usd = credit * s
    # 审计 A-2：credit/s 含 NaN 时显式传播 NaN，避免 max(nan, 0.0)=0.0 假值
    if not _finite(credit, s):
        max_loss_usd = float("nan")
    else:
        max_loss_usd = max(width_usd - credit_usd, 0.0)
    if kind.upper() == "CALL":
        im = im_short_call(s, short_k, short_mark)
    else:
        im = im_short_put(s, short_k, short_mark)
    return {
        "credit": credit,
        "credit_usd": credit_usd,
        "max_loss_usd": max_loss_usd,
        "im_standard": im,
        "im_standard_usd": _usd(im, s),
        "roi_on_max_loss": (credit_usd / max_loss_usd) if max_loss_usd > 0 else None,
        "estimate": True,
    }


def margin_iron_condor(
    s: float,
    put_long_k: float, put_short_k: float,
    call_short_k: float, call_long_k: float,
    put_short_mark: float, put_long_mark: float,
    call_short_mark: float, call_long_mark: float,
) -> Dict:
    """铁秃鹰（卖 put 价差 + 卖 call 价差，同一到期）。

    到期只有一侧可能亏损 → max_loss(USD) = 较宽侧翼宽 − 总权利金·S。
    im_standard = 两条 short 腿官方 IM 之和（标准账户无组合减免）。
    """
    credit = (put_short_mark - put_long_mark) + (call_short_mark - call_long_mark)
    credit_usd = credit * s
    put_width_usd = abs(put_short_k - put_long_k)
    call_width_usd = abs(call_short_k - call_long_k)
    # 审计 A-2：credit/s 含 NaN 时显式传播 NaN，避免 max(nan, 0.0)=0.0 假值
    if not _finite(credit, s):
        max_loss_usd = float("nan")
    else:
        max_loss_usd = max(max(put_width_usd, call_width_usd) - credit_usd, 0.0)
    im = im_short_put(s, put_short_k, put_short_mark) + im_short_call(s, call_short_k, call_short_mark)
    return {
        "credit": credit,
        "credit_usd": credit_usd,
        "put_width_usd": put_width_usd,
        "call_width_usd": call_width_usd,
        "max_loss_usd": max_loss_usd,
        "im_standard": im,
        "im_standard_usd": _usd(im, s),
        "roi_on_max_loss": (credit_usd / max_loss_usd) if max_loss_usd > 0 else None,
        "estimate": True,
    }


def margin_strangle_short(
    s: float, k_put: float, k_call: float,
    put_mark: float, call_mark: float,
) -> Dict:
    """裸卖宽跨（short OTM put + short OTM call，无保护腿）。

    理论亏损无限，max_loss 返回 None；im_standard = 两腿官方 IM 之和。
    roi_on_im 仅供排序参考，不代表真实风险回报（尾部风险需另由 RND 度量）。
    """
    credit = put_mark + call_mark
    im = im_short_put(s, k_put, put_mark) + im_short_call(s, k_call, call_mark)
    return {
        "credit": credit,
        "credit_usd": credit * s,
        "max_loss_usd": None,
        "im_standard": im,
        "im_standard_usd": _usd(im, s),
        "roi_on_im": (credit / im) if im and im > 0 else None,
        "estimate": True,
    }
