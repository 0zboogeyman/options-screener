import { useId, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { payoffCurve, PayoffLeg } from '../lib/payoff';

/**
 * 到期/估值日 P&L 曲线（纯 SVG，无依赖）。
 * 配色按中国习惯：盈=红、亏=绿。零轴灰色虚线，当前价蓝色虚线。
 */

interface Props {
  legs: PayoffLeg[];
  spot: number | null;   // 审计 Q-1：后端可为 null，组件内渲染占位
  offsetYears: number;   // 估值时点（年）：到期日传 legs[0].t_years
  height?: number;
}

function fmt(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 10000) return (v / 1000).toFixed(1) + 'k';
  return v.toFixed(0);
}

export default function PayoffChart({ legs, spot, offsetYears, height = 180 }: Props) {
  const { t } = useTranslation();
  // 审计 Q-6：clipPath id 加 useId 前缀，避免同页多图全局 id 冲突串扰
  const clipId = useId();
  const clipAboveId = `pnl-above-${clipId}`;
  const clipBelowId = `pnl-below-${clipId}`;
  const spotVal = spot ?? 0;   // 审计 Q-1：null 收窄为 number（无效时 invalid 分支提前返回）
  const { path, areaPath, zeroY, spotX, maxProfit, maxLoss, xLo, xHi, yMin, yMax, W, H, padL, padR, invalid } = useMemo(() => {
    const { points, maxProfit, maxLoss } = payoffCurve(legs, spot, offsetYears);
    const W = 640;
    const H = height;
    const padL = 56, padR = 12, padT = 14, padB = 22;
    // 审计 Q-1：spot 无效/无腿（payoffCurve 返回空点集）时不渲染曲线
    if (points.length === 0) {
      return { invalid: true, path: '', areaPath: '', zeroY: 0, spotX: 0,
               maxProfit: 0, maxLoss: 0, xLo: 0, xHi: 0, yMin: 0, yMax: 0,
               W, H, padL, padR };
    }
    const xLo = points[0].price;
    const xHi = points[points.length - 1].price;

    // y 域：P&L 范围上下各留 8%
    let yMin = maxLoss, yMax = maxProfit;
    if (!(yMax > yMin)) { yMax = Math.abs(yMin) || 1; yMin = -yMax; }
    const pad = (yMax - yMin) * 0.08;
    yMin -= pad; yMax += pad;

    const sx = (p: number) => padL + ((p - xLo) / (xHi - xLo)) * (W - padL - padR);
    const sy = (v: number) => padT + (1 - (v - yMin) / (yMax - yMin)) * (H - padT - padB);

    const path = points
      .map((pt, i) => `${i === 0 ? 'M' : 'L'}${sx(pt.price).toFixed(1)},${sy(pt.pnl).toFixed(1)}`)
      .join(' ');
    // 封闭区域（曲线 + 零轴），配合 clipPath 分别染盈/亏区
    const areaPath = `${path} L${(W - padR).toFixed(1)},${sy(0).toFixed(1)} L${padL.toFixed(1)},${sy(0).toFixed(1)} Z`;

    return {
      invalid: false,
      path, areaPath,
      zeroY: sy(0),
      spotX: sx(spotVal),
      maxProfit, maxLoss, xLo, xHi, yMin, yMax, W, H, padL, padR,
    };
  }, [legs, spot, offsetYears, height]);

  const padT = 14, padB = 22;

  if (invalid) {
    return (
      <div style={{ padding: '12px 16px', color: '#999', fontSize: 13 }}>
        {'—'}
      </div>
    );
  }

  return (
    <div style={{ width: '100%', maxWidth: 720 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        <defs>
          <clipPath id={clipAboveId}><rect x={padL} y={0} width={W - padL - padR} height={zeroY} /></clipPath>
          <clipPath id={clipBelowId}><rect x={padL} y={zeroY} width={W - padL - padR} height={H - zeroY} /></clipPath>
        </defs>
        {/* 盈亏区域填充（盈=红、亏=绿，中国习惯） */}
        <path d={areaPath} fill="#E24B4A" opacity={0.12} clipPath={`url(#${clipAboveId})`} />
        <path d={areaPath} fill="#639922" opacity={0.12} clipPath={`url(#${clipBelowId})`} />
        {/* 零轴 */}
        <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="#999" strokeDasharray="4 3" strokeWidth={0.8} />
        {/* 当前价 */}
        <line x1={spotX} y1={padT} x2={spotX} y2={H - padB} stroke="#185FA5" strokeDasharray="5 3" strokeWidth={1} />
        <text x={spotX} y={padT - 3} fontSize={10} fill="#185FA5" textAnchor="middle">
          {t('payoff.spotLabel', { value: fmt(spotVal) })}
        </text>
        {/* P&L 曲线 */}
        <path d={path} fill="none" stroke="#534AB7" strokeWidth={1.8} />
        {/* 轴标注 */}
        <text x={padL - 6} y={padT + 8} fontSize={10} fill="#A32D2D" textAnchor="end">
          +{fmt(maxProfit)}
        </text>
        <text x={padL - 6} y={H - padB} fontSize={10} fill="#3B6D11" textAnchor="end">
          {fmt(maxLoss)}
        </text>
        <text x={padL} y={H - 6} fontSize={10} fill="#666" textAnchor="middle">{fmt(xLo)}</text>
        <text x={W - padR} y={H - 6} fontSize={10} fill="#666" textAnchor="middle">{fmt(xHi)}</text>
        <text x={padL - 6} y={zeroY + 3} fontSize={10} fill="#999" textAnchor="end">0</text>
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#888', marginTop: 2 }}>
        <span>{t('payoff.expiryLabel')}</span>
        <span>
          <span style={{ color: '#A32D2D' }}>{t('payoff.maxProfit', { value: fmt(maxProfit) })}</span>
          {' · '}
          <span style={{ color: '#3B6D11' }}>{t('payoff.maxLoss', { value: fmt(maxLoss) })}</span>
        </span>
      </div>
    </div>
  );
}
