/** Payoff 曲线计算：与后端 bs.py 同口径（r=0，USD）。
 *
 *  P&L(S_T) = Σ sign·legValue(S_T) − Σ sign·premium_usd
 *  premium_usd = 腿价(币) × 当前 spot（与扫描器 credit_usd 口径一致，
 *  忽略逆向期权凸性的近似，和 margin.py / multi_leg.py 相同）。
 *
 *  估值时点用 offsetYears 统一表达：
 *    IC/Strangle 传 legs[0].t_years（到期日，全部腿按内在价值）；
 *    Calendar 传近月 t_years（近月到期日：近月腿内在、远月腿 BS 剩余期限估值）。
 */

export interface PayoffLeg {
  kind: string;      // "CALL" | "PUT"
  side: string;      // "buy" | "sell"
  strike: number;
  price: number;     // 币本位单价
  iv?: number;       // BS 估值用（年化波动率，小数）
  t_years?: number;  // 当前剩余期限（年）
}

/** 标准正态 CDF（Abramowitz–Stegun 26.2.17，|ε|<1.5e-7） */
export function normCdf(x: number): number {
  if (!isFinite(x)) return x > 0 ? 1 : 0;
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * ax);
  const erf = sign * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-ax * ax));
  return 0.5 * (1 + erf);
}

/** BS 价格（r=0，USD 口径），与后端 price_call_vec/price_put_vec 一致 */
export function bsPrice(kind: string, s: number, k: number, iv: number, t: number): number {
  if (s <= 0 || k <= 0 || iv <= 0 || t <= 0) return NaN;
  const vt = iv * Math.sqrt(t);
  const d1 = (Math.log(s / k) + 0.5 * iv * iv * t) / vt;
  const d2 = d1 - vt;
  return kind.toUpperCase() === 'CALL'
    ? s * normCdf(d1) - k * normCdf(d2)
    : k * normCdf(-d2) - s * normCdf(-d1);
}

function legValue(leg: PayoffLeg, sT: number, tRemain: number): number {
  const sign = leg.side === 'buy' ? 1 : -1;
  if (tRemain <= 1e-6) {
    const intrinsic = leg.kind.toUpperCase() === 'CALL'
      ? Math.max(sT - leg.strike, 0)
      : Math.max(leg.strike - sT, 0);
    return sign * intrinsic;
  }
  const v = bsPrice(leg.kind, sT, leg.strike, leg.iv ?? 0.5, tRemain);
  return sign * (isFinite(v) ? v : 0);
}

export interface PayoffPoint { price: number; pnl: number; }

/** 组合在标的价格 sT 处的 P&L（USD，offsetYears 为估值时点） */
export function portfolioPnlAt(
  legs: PayoffLeg[],
  sT: number,
  spot: number,
  offsetYears: number,
): number {
  const netPremiumUsd = legs.reduce(
    (acc, l) => acc + (l.side === 'buy' ? -1 : 1) * l.price * spot, 0,
  );
  let pnl = netPremiumUsd;
  for (const l of legs) {
    pnl += legValue(l, sT, (l.t_years ?? 0) - offsetYears);
  }
  return pnl;
}

/** BS delta（r=0）：call=N(d1)，put=N(d1)−1 */
export function bsDelta(kind: string, s: number, k: number, iv: number, t: number): number {
  if (s <= 0 || k <= 0 || iv <= 0 || t <= 0) return NaN;
  const vt = iv * Math.sqrt(t);
  const d1 = (Math.log(s / k) + 0.5 * iv * iv * t) / vt;
  const dc = normCdf(d1);
  return kind.toUpperCase() === 'CALL' ? dc : dc - 1;
}

/** 组合净 Delta（张数，buy=+1 sell=−1 加权）；到期腿按 0/±1 阶梯近似 */
export function portfolioDeltaAt(legs: PayoffLeg[], sT: number, offsetYears: number): number {
  let d = 0;
  for (const l of legs) {
    const sign = l.side === 'buy' ? 1 : -1;
    const tRemain = (l.t_years ?? 0) - offsetYears;
    let ld: number;
    if (tRemain <= 1e-6) {
      const itm = l.kind.toUpperCase() === 'CALL' ? sT > l.strike : sT < l.strike;
      ld = itm ? (l.kind.toUpperCase() === 'CALL' ? 1 : -1) : 0;
    } else {
      ld = bsDelta(l.kind, sT, l.strike, l.iv ?? 0.5, tRemain);
      if (!isFinite(ld)) ld = 0;
    }
    d += sign * ld;
  }
  return d;
}

/** 组合 P&L 曲线：offsetYears 为估值时点（距现在的年数） */
export function payoffCurve(
  legs: PayoffLeg[],
  spot: number,
  offsetYears: number,
  n: number = 160,
): { points: PayoffPoint[]; maxProfit: number; maxLoss: number } {
  const strikes = legs.map(l => l.strike);
  const lo = Math.max(Math.min(...strikes, spot) * 0.8, 1e-6);
  const hi = Math.max(...strikes, spot) * 1.2;

  // 净权利金（USD，正=净收入）
  const netPremiumUsd = legs.reduce(
    (acc, l) => acc + (l.side === 'buy' ? -1 : 1) * l.price * spot, 0,
  );

  const points: PayoffPoint[] = [];
  let maxProfit = -Infinity;
  let maxLoss = Infinity;
  for (let i = 0; i <= n; i++) {
    const sT = lo + (hi - lo) * (i / n);
    let pnl = netPremiumUsd;
    for (const l of legs) {
      const tRemain = (l.t_years ?? 0) - offsetYears;
      pnl += legValue(l, sT, tRemain);
    }
    points.push({ price: sT, pnl });
    if (pnl > maxProfit) maxProfit = pnl;
    if (pnl < maxLoss) maxLoss = pnl;
  }
  return { points, maxProfit, maxLoss };
}
