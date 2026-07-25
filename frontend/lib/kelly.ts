/** Kelly 仓位建议（简化版）。
 *
 *  f* = p − q/b，p=胜率，q=1−p，b=赔率（盈利/亏损，USD 口径）。
 *  显示 1/4 Kelly（fractional Kelly，降低估计误差带来的爆仓风险）。
 *  f*<0（负期望）时按 0 处理并提示。
 *
 *  仅对贷方/有明确 max_loss 的策略展示（IC、short strangle、CSP、垂直价差）；
 *  借方多波动策略（long strangle、calendar）与 CC（损失源于持仓而非策略）
 *  的赔率结构不适用二元 Kelly，不显示。
 */

export function kellyFraction(p: number | null | undefined, b: number | null | undefined): number {
  if (p == null || b == null || !(p > 0 && p < 1) || !(b > 0) || !isFinite(b)) return NaN;
  return Math.max(p - (1 - p) / b, 0);
}

/** 返回 {pct: 显示文本, negative: 是否零值（Kelly 为 0 提示勿重仓）} */
export function quarterKelly(
  p: number | null | undefined,
  b: number | null | undefined,
): { pct: string; zero: boolean } {
  const f = kellyFraction(p, b);
  if (!isFinite(f)) return { pct: '—', zero: false };
  if (f <= 0) return { pct: '0%', zero: true };
  return { pct: ((f / 4) * 100).toFixed(1) + '%', zero: false };
}
