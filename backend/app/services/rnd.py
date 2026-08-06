"""SVI 隐含风险中性密度（RND）：POP / 分位数 / 期望亏损（ES）。

理论（Breeden-Litzenberger 在 SVI 参数化下的闭式形式）：
令 x = ln(S_T/F)，w(k) 为 SVI 总方差，d2(k) = −k/√w − √w/2，则 x 的
隐含概率密度为

    f(x) = g(x) · n(d2(x)) / √w(x)

其中 g(k) 即 svi.butterfly_g——这也解释了「g(k)≥0 ⟺ 无蝶式套利」：
密度处处非负。平 SVI（b=0）时 g≡1，密度退化为对数正态。

用途：替代蒙特卡洛。对欧式终端收益策略（铁秃鹰/宽跨/价差），PoP、
VaR、CVaR 都可由该密度的数值积分一次算清，且天然含微笑肥尾
（对数正态会低估尾部，crypto 尤其明显）。

输出自检：mass（归一化前积分，应≈1）、fwd_dev（E[S_T]/F−1，应≈0）。
偏差大说明该切片拟合质量差，调用方可降级到 BS 对数正态。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
from scipy.stats import norm

from .svi import butterfly_g, raw_svi_w

# numpy 1.26 只有 trapz，2.x 改名 trapezoid；兼容两者
_trapezoid = getattr(np, "trapezoid", None) or np.trapz

# 密度网格（对数货币度）：默认按 ATM 总方差动态扩展，见 rnd_from_svi。
# 固定 ±3 覆盖 F·e^±3 ≈ [5%, 2000%] 的价格范围（显式传 k_range 时使用）
_DEFAULT_N_GRID = 2401


@dataclass
class RND:
    """x = ln(S_T/F) 上的隐含密度（已归一化）。"""
    k: np.ndarray          # 网格点（升序）
    price: np.ndarray      # F·e^k
    pdf: np.ndarray        # k 空间密度（积分=1）
    cdf: np.ndarray        # 累积分布 0..1
    forward: float
    t_years: float
    mass: float            # 归一化前积分（自检，应≈1）
    fwd_dev: float         # E[S_T]/F − 1（自检，应≈0）


def rnd_from_svi(
    params: Dict,
    t_years: float,
    forward: float,
    k_range: Optional[tuple] = None,
    n_grid: int = _DEFAULT_N_GRID,
) -> RND:
    """由 SVI 切片参数构建隐含密度网格。

    params: fit_svi_slice 返回的 a/b/rho/m/sigma（quality 须为 ok）。
    k_range: 显式对数货币度范围；None 时按 ATM 总方差动态扩展至
        ±max(3, 4·√w_atm+1)——高波动/长期限切片固定 ±3 会截断尾部，
        导致 ES / 尾部概率系统性低估（审计 M2 修复）。
    """
    a, b, rho, m, sigma = (params[k2] for k2 in ("a", "b", "rho", "m", "sigma"))
    if k_range is None:
        w_atm = float(raw_svi_w(np.array([0.0]), a, b, rho, m, sigma)[0])
        half = max(3.0, 4.0 * math.sqrt(max(w_atm, 1e-12)) + 1.0)
        k_range = (-half, half)
    k = np.linspace(k_range[0], k_range[1], n_grid)
    w = np.maximum(raw_svi_w(k, a, b, rho, m, sigma), 1e-12)
    d2 = -k / np.sqrt(w) - 0.5 * np.sqrt(w)
    g = butterfly_g(k, a, b, rho, m, sigma)

    pdf = g * norm.pdf(d2) / np.sqrt(w)
    pdf = np.where(np.isfinite(pdf) & (pdf > 0), pdf, 0.0)

    mass = float(_trapezoid(pdf, k))
    if mass > 1e-12:
        pdf = pdf / mass

    price = forward * np.exp(k)
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[1:] + pdf[:-1]) * np.diff(k))])
    cdf = np.clip(cdf, 0.0, 1.0)

    mean_price = float(_trapezoid(price * pdf, k))
    fwd_dev = mean_price / forward - 1.0 if forward > 0 else float("nan")

    return RND(k=k, price=price, pdf=pdf, cdf=cdf, forward=forward,
               t_years=t_years, mass=mass, fwd_dev=fwd_dev)


def rnd_is_valid(rnd: RND, mass_tol: float = 0.1, fwd_tol: float = 0.05) -> bool:
    """RND 质量自检：归一化前 mass 应 ≈ 1、远期偏差应 ≈ 0。

    偏差超过容差说明该切片 SVI 拟合质量差（密度尾部泄漏 / 远期失真），
    调用方应跳过该到期，避免基于错误密度计算 PoP / 尾部风险。
    """
    if not np.isfinite(rnd.mass) or not np.isfinite(rnd.fwd_dev):
        return False
    if abs(rnd.mass - 1.0) > mass_tol:
        return False
    if abs(rnd.fwd_dev) > fwd_tol:
        return False
    return True


def _cdf_at(rnd: RND, price: float) -> float:
    if rnd.forward <= 0:
        return float("nan")
    if price <= 0:
        return 0.0
    x = math.log(price / rnd.forward)
    return float(np.interp(x, rnd.k, rnd.cdf, left=0.0, right=1.0))


def prob_ge(rnd: RND, price: float) -> float:
    """P(S_T ≥ price)。"""
    return 1.0 - _cdf_at(rnd, price)


def prob_between(rnd: RND, price_lo: float, price_hi: float) -> float:
    """P(S_T ∈ [lo, hi])：铁秃鹰/卖出宽跨的 PoP。"""
    if price_hi <= price_lo:
        return float("nan")
    return _cdf_at(rnd, price_hi) - _cdf_at(rnd, price_lo)


def quantile(rnd: RND, q: float) -> float:
    """价格的 q 分位数（q∈(0,1)，如 q=0.05 为 5% VaR 价位）。"""
    if not (0.0 < q < 1.0):
        return float("nan")
    x = float(np.interp(q, rnd.cdf, rnd.k))
    return rnd.forward * math.exp(x)


def _cum_moment_price(rnd: RND) -> np.ndarray:
    """M(k) = ∫_{-∞}^{k} price(x)·pdf(x) dx（一阶矩累积）。"""
    integrand = rnd.price * rnd.pdf
    return np.concatenate([[0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(rnd.k))])


def expected_shortfall(rnd: RND, q: float = 0.05) -> float:
    """下尾期望亏损价位 E[S_T | S_T ≤ q 分位]（put 侧 CVaR，USD 价）。"""
    if not (0.0 < q < 1.0):
        return float("nan")
    m = _cum_moment_price(rnd)
    x_q = math.log(quantile(rnd, q) / rnd.forward)
    m_at = float(np.interp(x_q, rnd.k, m))
    return m_at / q


def expected_upside_tail(rnd: RND, q: float = 0.05) -> float:
    """上尾期望价位 E[S_T | S_T ≥ (1−q) 分位]（call 侧 CVaR，USD 价）。"""
    if not (0.0 < q < 1.0):
        return float("nan")
    m = _cum_moment_price(rnd)
    x_q = math.log(quantile(rnd, 1.0 - q) / rnd.forward)
    m_at = float(np.interp(x_q, rnd.k, m))
    total = m[-1]
    return (total - m_at) / q
