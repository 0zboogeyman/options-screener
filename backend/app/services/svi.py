"""Raw SVI 波动率微笑拟合（每个到期日切片独立拟合）。

模型（Gatheral raw SVI），k = ln(K/F) 为对数货币度，w = iv²·T 为总隐含方差：

    w(k) = a + b · (ρ·(k−m) + √((k−m)² + σ²))

参数语义：a 整体水平、b 两翼斜率、ρ 偏度（crypto 通常 <0，put 翼更陡）、
m 水平位移、σ 曲率平滑度。

每个切片输出：
  * 五参数 + 拟合质量（rmse、引用报价数）
  * atm_iv：k=0（K=F）处的隐含波动率
  * rr25 / bf25：25Δ risk reversal 与 butterfly（在拟合曲线上用 BS delta
    反解 25Δ 行权点），作为 skew 的结构化度量
  * quality：ok / insufficient / fit_failed / arb_violation
    非 ok 时调用方应回退到原始 mark_iv 逻辑。

无套利校验：
  * 总方差非负：min_k w(k) = a + b·σ·√(1−ρ²) ≥ 0
  * butterfly 套利（Gatheral & Jacquier 充分条件）：g(k) ≥ 0，
    g(k) = (1 − k·w'/2w)² − (w'/2)²·(1/w + 1/4) + w''/2

注意：日历套利（跨切片）不在此处校验，属于曲面级约束，本模块只保证单切片合法。
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Optional, Sequence

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import norm

logger = logging.getLogger(__name__)

# 参数边界 [a, b, rho, m, sigma]
_LOWER = np.array([-5.0, 0.0, -0.999, -3.0, 1e-4])
_UPPER = np.array([5.0, 5.0, 0.999, 3.0, 5.0])

# 拟合所需的最少有效报价数（5 参数模型，<5 点必然欠定）
MIN_QUOTES = 5
# butterfly g(k) 容差：数值拟合噪声下允许微小为负
_ARB_TOL = -1e-4


def raw_svi_w(k, a: float, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    """raw SVI 总方差 w(k)，k 支持数组。"""
    k = np.asarray(k, dtype=float)
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))


def svi_iv(k, params: Dict, t_years: float) -> np.ndarray:
    """由拟合参数给出 iv(k)（小数形式），k 支持数组。"""
    w = raw_svi_w(k, params["a"], params["b"], params["rho"], params["m"], params["sigma"])
    w = np.maximum(w, 1e-12)
    return np.sqrt(w / max(t_years, 1e-9))


def _svi_dw_dk(k, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    """w 对 k 的一阶导数。"""
    return b * (rho + (k - m) / np.sqrt((k - m) ** 2 + sigma ** 2))


def _svi_d2w_dk2(k, b: float, m: float, sigma: float) -> np.ndarray:
    """w 对 k 的二阶导数。"""
    return b * sigma ** 2 / ((k - m) ** 2 + sigma ** 2) ** 1.5


def butterfly_g(k, a: float, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    """Gatheral & Jacquier butterfly 无套利充分条件 g(k)，需 ≥ 0。"""
    k = np.asarray(k, dtype=float)
    w = np.maximum(raw_svi_w(k, a, b, rho, m, sigma), 1e-12)
    dw = _svi_dw_dk(k, b, rho, m, sigma)
    d2w = _svi_d2w_dk2(k, b, m, sigma)
    return (1.0 - k * dw / (2.0 * w)) ** 2 - (dw / 2.0) ** 2 * (1.0 / w + 0.25) + d2w / 2.0


def _min_total_variance(a: float, b: float, rho: float, sigma: float) -> float:
    """min_k w(k) 的解析值（非负性校验）。"""
    return a + b * sigma * math.sqrt(max(1.0 - rho ** 2, 0.0))


def _arb_grid(k_min: float, k_max: float) -> np.ndarray:
    """g(k) 校验网格：覆盖数据范围并向两侧外延，至少 ±1.5。

    固定 ±2.5 对长到期切片过严（深度外推区无报价约束，形状轻微失真即误判），
    而对定价有实际意义的区域集中在报价覆盖范围附近。
    """
    lo = min(-1.5, k_min - 0.3)
    hi = max(1.5, k_max + 0.3)
    return np.linspace(lo, hi, 201)


def _check_no_arbitrage(params: Dict, k_min: float = -1.5, k_max: float = 1.5) -> bool:
    """True = 无套利违规。"""
    a, b, rho, m, sigma = (params[k] for k in ("a", "b", "rho", "m", "sigma"))
    if _min_total_variance(a, b, rho, sigma) < 0.0:
        return False
    g = butterfly_g(_arb_grid(k_min, k_max), a, b, rho, m, sigma)
    return bool(np.all(g >= _ARB_TOL))


def _initial_guess(k: np.ndarray, w_obs: np.ndarray) -> np.ndarray:
    """启发式初值：m 取最低总方差点，其余取温和中性值。"""
    i_min = int(np.argmin(w_obs))
    m0 = float(np.clip(k[i_min], _LOWER[3] + 1e-3, _UPPER[3] - 1e-3))
    b0 = 0.1
    rho0 = 0.0
    sigma0 = 0.1
    a0 = float(np.clip(w_obs[i_min] - b0 * sigma0, _LOWER[0] + 1e-3, _UPPER[0] - 1e-3))
    return np.array([a0, b0, rho0, m0, sigma0])


def _strike_at_call_delta(params: Dict, t_years: float, target_call_delta: float) -> Optional[float]:
    """在拟合曲线上反解使 BS call delta 等于目标值的 k（对数货币度）。

    d1(k) = (−k + 0.5·w(k)) / √w(k)，目标 d1* = N⁻¹(Δ)。
    曲线 d1(k) 在合理参数下关于 k 单调递减，用二分法求解。
    """
    d1_target = norm.ppf(target_call_delta)

    def d1_at(k_scalar: float) -> float:
        w = float(raw_svi_w(np.array([k_scalar]), params["a"], params["b"],
                            params["rho"], params["m"], params["sigma"])[0])
        w = max(w, 1e-12)
        return (-k_scalar + 0.5 * w) / math.sqrt(w)

    lo, hi = -2.5, 2.5
    f_lo, f_hi = d1_at(lo) - d1_target, d1_at(hi) - d1_target
    if f_lo * f_hi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f_mid = d1_at(mid) - d1_target
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def fit_svi_slice(
    strikes: Sequence[float],
    ivs: Sequence[float],
    ois: Sequence[float],
    forward: float,
    t_years: float,
    min_quotes: int = MIN_QUOTES,
) -> Dict:
    """拟合单个到期日切片的 raw SVI。

    参数：
        strikes/ivs/ois: 该到期日的行权价、mark_iv（小数形式）、持仓量
        forward: 该到期对应标的价格（用链上 underlying 中位数近似远期价）
        t_years: 年化剩余期限

    返回 dict：a/b/rho/m/sigma、atm_iv、rr25、bf25、rmse_iv、n_quotes、quality。
    quality != "ok" 时参数字段为 None，调用方回退到 mark_iv。
    """
    base: Dict = {
        "a": None, "b": None, "rho": None, "m": None, "sigma": None,
        "atm_iv": None, "rr25": None, "bf25": None,
        "rmse_iv": None, "n_quotes": 0, "quality": "insufficient",
    }

    k_all = np.log(np.asarray(strikes, dtype=float) / max(forward, 1e-9))
    iv = np.asarray(ivs, dtype=float)
    oi = np.asarray(ois, dtype=float)

    # 有效报价：iv 在合理区间（1%–300%）；OI 仅影响权重，缺失按 0
    valid = np.isfinite(iv) & (iv > 0.01) & (iv < 3.0) & np.isfinite(k_all)
    if int(valid.sum()) < min_quotes:
        return base

    k, iv_v = k_all[valid], iv[valid]
    oi_v = np.where(np.isfinite(oi[valid]), oi[valid], 0.0)
    w_obs = iv_v ** 2 * t_years
    # OI 开根号加权：照顾流动性又不让巨鲸合约淹没微笑形状
    wgt = np.sqrt(np.maximum(oi_v, 0.0) + 1.0)

    # 归一化：w = iv²·T 跨期限相差两个数量级，短到期切片 w~1e-4，
    # 直接拟合时 trf 的尺度/容差失调会造成假 fit_failed。
    # 按中位数归一化拟合，完成后把 a、b 还原（rho/m/sigma 不受缩放影响）。
    w_med = max(float(np.median(w_obs)), 1e-6)
    wn = w_obs / w_med

    def resid(p: np.ndarray) -> np.ndarray:
        return (raw_svi_w(k, *p) - wn) * wgt

    # 多初值：启发式 + 两个先验（crypto 常见负 rho / 中性）。
    # 在收敛解中优先选无套利解，避免落入退化参数区。
    x0s = [
        _initial_guess(k, wn),
        np.array([max(float(wn.min()) * 0.5, 1e-4), 0.05, -0.3, 0.0, 0.2]),
        np.array([max(float(wn.min()), 1e-4), 0.3, 0.0, float(np.median(k)), 0.4]),
    ]
    x0s = [np.clip(x, _LOWER + 1e-4, _UPPER - 1e-4) for x in x0s]

    candidates = []
    for x0 in x0s:
        try:
            sol = least_squares(resid, x0, bounds=(_LOWER, _UPPER), method="trf",
                                x_scale="jac", max_nfev=5000)
        except Exception:
            continue
        if not sol.success:
            continue
        p = {"a": float(sol.x[0]) * w_med, "b": float(sol.x[1]) * w_med,
             "rho": float(sol.x[2]), "m": float(sol.x[3]), "sigma": float(sol.x[4])}
        candidates.append((float(sol.cost), p))

    if not candidates:
        return {**base, "n_quotes": int(valid.sum()), "quality": "fit_failed"}

    k_min, k_max = float(k.min()), float(k.max())
    arb_free = [(c, p) for c, p in candidates if _check_no_arbitrage(p, k_min, k_max)]
    if not arb_free:
        best = min(candidates, key=lambda t: t[0])[1]
        logger.info("SVI arbitrage violation (a=%.4f b=%.4f rho=%.3f m=%.3f sigma=%.4f)",
                    best["a"], best["b"], best["rho"], best["m"], best["sigma"])
        return {**base, "n_quotes": int(valid.sum()), "quality": "arb_violation"}

    params = min(arb_free, key=lambda t: t[0])[1]

    w_model = raw_svi_w(k, params["a"], params["b"], params["rho"], params["m"], params["sigma"])
    rmse_iv = float(np.sqrt(np.mean((np.sqrt(np.maximum(w_model, 1e-12) / t_years) - iv_v) ** 2)))

    atm_iv = float(svi_iv(np.array([0.0]), params, t_years)[0])

    # 25Δ 点：OTM call 对应 call delta 0.25（k>0），OTM put 对应 call delta 0.75（k<0）
    rr25 = bf25 = None
    k_c25 = _strike_at_call_delta(params, t_years, 0.25)
    k_p25 = _strike_at_call_delta(params, t_years, 0.75)
    if k_c25 is not None and k_p25 is not None:
        iv_c25 = float(svi_iv(np.array([k_c25]), params, t_years)[0])
        iv_p25 = float(svi_iv(np.array([k_p25]), params, t_years)[0])
        rr25 = iv_c25 - iv_p25
        bf25 = 0.5 * (iv_c25 + iv_p25) - atm_iv

    return {
        **params,
        "atm_iv": atm_iv, "rr25": rr25, "bf25": bf25,
        "rmse_iv": rmse_iv, "n_quotes": int(valid.sum()), "quality": "ok",
    }
