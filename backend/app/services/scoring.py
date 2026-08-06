"""统一评分管道：锚定区间归一化 + 加权合成 + MIN_SCORE 过滤。

审计 M6/M5 修复：
  * 归一化使用固定参考区间 (lo, hi) 而非候选集动态 min-max——分数不再随
    候选集变化漂移，MIN_SCORE 具备绝对语义（可跨候选集解释）；
  * ivp_score 本身是 0-1 绝对量，按 (0,1) 归一化等价于直接入分；
  * 供 single_leg / multi_leg / scanner 共用，消除重复实现与私有跨模块导入。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

# 综合评分低于该阈值的候选直接不展示（需求：评分 45 分以下的策略过滤掉）
MIN_SCORE = 45.0

# 评分权重规格：("field", weight, invert, (lo, hi))
#   invert=True 表示值越小越好（如 assign_prob、cost_ratio、debit_ratio）
#   (lo, hi) 为锚定归一化参考区间，区间外钳制到 0/1
WeightSpec = Tuple[str, float, bool, Tuple[float, float]]


def normalize_score(values: List[float], lo: float, hi: float) -> List[float]:
    """锚定区间归一化：v ∈ [lo, hi] → [0, 1]，区间外钳制到 0/1。"""
    if not values:
        return []
    span = hi - lo
    if span <= 0:
        span = 1.0
    out = []
    for v in values:
        if v is None or not np.isfinite(v):
            out.append(0.0)
        else:
            out.append(max(0.0, min(1.0, (v - lo) / span)))
    return out


def apply_scores(candidates: List[Dict], weights: Tuple[WeightSpec, ...]) -> None:
    """加权打分 → 写入 c["score"] → 降序排序 → 过滤掉评分低于 MIN_SCORE 的候选（原地）。

    ivp_score 缺省按 0.5（中性）入分：该字段 0-1 区间绝对值直接参与合成。
    """
    totals = [0.0] * len(candidates)
    for key, weight, invert, (lo, hi) in weights:
        raw = []
        for c in candidates:
            v = c.get(key)
            if v is None or not isinstance(v, (int, float)) or not np.isfinite(v):
                v = 0.5 if key == "ivp_score" else float("nan")
            raw.append((1.0 - v) if invert and np.isfinite(v) else v)
        norm = normalize_score(raw, lo, hi)
        for i in range(len(candidates)):
            totals[i] += weight * norm[i]
    for i, c in enumerate(candidates):
        c["score"] = round(totals[i] * 100, 1)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates[:] = [c for c in candidates if c["score"] >= MIN_SCORE]
