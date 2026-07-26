import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { PayoffLeg, portfolioPnlAt, portfolioDeltaAt } from '../lib/payoff';

/** 现货冲击情景分析：±5%/±10% 下组合 MTM P&L（BS 重估，当前快照 t 不变）
 *  与净 Delta 变化。盈=红、亏=绿（中国习惯）。
 *
 *  用途：回答「如果明天现货跳变 ±10%，这个仓位浮盈/浮亏多少」——
 *  与 PayoffChart（到期日内在价值）互补，这个是持有期市值视角。
 */

interface Props {
  legs: PayoffLeg[];
  spot: number;
}

const SHOCKS = [-0.10, -0.05, 0, 0.05, 0.10];

function fmtUsd(v: number): string {
  const sign = v >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export default function ScenarioTable({ legs, spot }: Props) {
  const { t } = useTranslation();
  const rows = useMemo(() => SHOCKS.map(shock => {
    const sT = spot * (1 + shock);
    return {
      shock,
      sT,
      pnl: portfolioPnlAt(legs, sT, spot, 0),
      delta: portfolioDeltaAt(legs, sT, 0),
    };
  }), [legs, spot]);

  return (
    <div style={{ minWidth: 260 }}>
      <strong>{t('scenario.title')}</strong>
      <table style={{ fontSize: 13, marginTop: 4, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ color: '#888' }}>
            <th style={{ textAlign: 'left', padding: '2px 10px 2px 0', fontWeight: 500 }}>{t('scenario.shock')}</th>
            <th style={{ textAlign: 'right', padding: '2px 10px', fontWeight: 500 }}>{t('scenario.spot')}</th>
            <th style={{ textAlign: 'right', padding: '2px 10px', fontWeight: 500 }}>{t('scenario.mtmPnl')}</th>
            <th style={{ textAlign: 'right', padding: '2px 0 2px 10px', fontWeight: 500 }}>{t('scenario.netDelta')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.shock} style={{ background: r.shock === 0 ? '#f5f5f5' : 'transparent' }}>
              <td style={{ padding: '2px 10px 2px 0' }}>
                {r.shock === 0 ? t('scenario.current') : `${r.shock > 0 ? '+' : ''}${(r.shock * 100).toFixed(0)}%`}
              </td>
              <td style={{ textAlign: 'right', padding: '2px 10px' }}>
                ${r.sT.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </td>
              <td style={{
                textAlign: 'right', padding: '2px 10px', fontWeight: 500,
                color: r.pnl >= 0 ? '#A32D2D' : '#3B6D11',
              }}>
                {fmtUsd(r.pnl)}
              </td>
              <td style={{ textAlign: 'right', padding: '2px 0 2px 10px' }}>
                {r.delta.toFixed(3)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
        {t('scenario.note')}
      </div>
    </div>
  );
}
