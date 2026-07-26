import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { CalendarResult } from '../types/api';
import PayoffChart from './PayoffChart';
import ScenarioTable from './ScenarioTable';
import { usePersistedState } from '../lib/usePersistedState';

const API_BASE = '/api';

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

interface Props {
  onDataUpdate?: (data: { asof_ts: number; spot_price?: number; dvol_index?: number; base?: 'BTC' | 'ETH' }) => void;
}

export default function CalendarScanner({ onDataUpdate }: Props) {
  const { t } = useTranslation();
  const [base, setBase] = usePersistedState<'BTC' | 'ETH'>('cal.base', 'BTC');
  const [nearDteMin, setNearDteMin] = usePersistedState('cal.nearDteMin', '7');
  const [nearDteMax, setNearDteMax] = usePersistedState('cal.nearDteMax', '30');
  const [minGapDays, setMinGapDays] = usePersistedState('cal.minGapDays', '14');
  const [strikeBandPct, setStrikeBandPct] = usePersistedState('cal.strikeBandPct', '0.10');
  const [minOi, setMinOi] = usePersistedState('cal.minOi', '10');
  const [pricingMode, setPricingMode] = usePersistedState<'mid' | 'conservative'>('cal.pricingMode', 'mid');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CalendarResult | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const handleScan = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/strategy/calendar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base,
          near_dte_min: parseInt(nearDteMin),
          near_dte_max: parseInt(nearDteMax),
          min_gap_days: parseInt(minGapDays),
          strike_band_pct: parseFloat(strikeBandPct),
          min_oi: parseInt(minOi),
          pricing_mode: pricingMode,
          return_count: 15,
        })
      });

      if (!resp.ok) {
        if (resp.status === 429) throw new Error(t('common.error429'));
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: CalendarResult = await resp.json();
      setResult(data);

      if (onDataUpdate && data.asof_ts) {
        onDataUpdate({
          asof_ts: data.asof_ts,
          spot_price: data.spot_price,
          dvol_index: data.dvol_index,
          base,
        });
      }
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="scanner-section">
      <h2 className="scanner-title">{t('calendar.title')}</h2>
      <p className="scanner-description">
        {t('calendar.description')}
      </p>

      <div className="filter-grid filter-grid-3">
        <label className="filter-label">
          <strong>{t('common.base')}</strong>
          <select className="filter-select" value={base} onChange={e => setBase(e.target.value as any)}>
            <option value="BTC">BTC</option>
            <option value="ETH">ETH</option>
          </select>
        </label>
        <label className="filter-label">
          <strong>{t('calendar.nearDteMin')}</strong>
          <input type="number" className="filter-input" value={nearDteMin} onChange={e => setNearDteMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('calendar.nearDteMax')}</strong>
          <input type="number" className="filter-input" value={nearDteMax} onChange={e => setNearDteMax(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('calendar.minGapDays')}</strong>
          <input type="number" className="filter-input" value={minGapDays} onChange={e => setMinGapDays(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('calendar.strikeBand')}</strong>
          <input type="number" step="0.01" className="filter-input" value={strikeBandPct} onChange={e => setStrikeBandPct(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('common.minOi')}</strong>
          <input type="number" className="filter-input" value={minOi} onChange={e => setMinOi(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('common.pricingMode')}</strong>
          <select className="filter-select" value={pricingMode} onChange={e => setPricingMode(e.target.value as any)}>
            <option value="mid">{t('common.pricingMid')}</option>
            <option value="conservative">{t('common.pricingConservative')}</option>
          </select>
        </label>
      </div>

      <button className="btn-primary" onClick={handleScan} disabled={loading}>
        {loading ? t('common.scanning') : t('common.scan')}
      </button>

      {error && <div className="error-message">{error}</div>}

      {result && result.candidates.length > 0 && (
        <div className="result-card">
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('calendar.nearFar')}</th>
                  <th className="align-right">{t('calendar.dteNearFar')}</th>
                  <th className="align-right">{t('common.strike')}</th>
                  <th className="align-right">{t('calendar.kind')}</th>
                  <th className="align-right">{t('calendar.cost')}</th>
                  <th className="align-right">{t('calendar.ivNearFar')}</th>
                  <th className="align-right">{t('calendar.ivSlope')}</th>
                  <th className="align-right">{t('calendar.thetaApr')}</th>
                  <th className="align-right">{t('calendar.profitZone')}</th>
                  <th className="align-right">{t('common.score')}</th>
                </tr>
              </thead>
              <tbody>
                {result.candidates.map((c, idx) => (
                  <>
                    <tr
                      key={idx}
                      onClick={() => setExpandedRow(expandedRow === idx ? null : idx)}
                      style={{
                        background: expandedRow === idx ? '#f0f8ff' : idx % 2 === 0 ? '#fff' : '#fafafa',
                        cursor: 'pointer'
                      }}
                    >
                      <td style={{ fontSize: 12 }}>
                        {c.expiry_near} → {c.expiry_far}
                      </td>
                      <td className="align-right">{c.dte_near} / {c.dte_far}</td>
                      <td className="align-right">${formatNumber(c.strike, 0)}</td>
                      <td className="align-right">{c.kind}</td>
                      <td className="align-right" style={{ color: '#dc3545' }}>${formatNumber(c.debit_usd, 2)}</td>
                      <td className="align-right" style={{ fontSize: 12 }}>
                        {(c.atm_iv_near * 100).toFixed(1)}% / {(c.atm_iv_far * 100).toFixed(1)}%
                      </td>
                      <td className="align-right" style={{ color: c.iv_slope > 0 ? '#28a745' : '#dc3545' }}>
                        {(c.iv_slope * 100).toFixed(2)}%
                      </td>
                      <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                        {c.theta_apr != null ? `${(c.theta_apr * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="align-right" style={{ fontSize: 12 }}>
                        {c.profit_zone.breakeven_lo != null && c.profit_zone.breakeven_hi != null
                          ? `${formatNumber(c.profit_zone.breakeven_lo, 0)} ~ ${formatNumber(c.profit_zone.breakeven_hi, 0)}`
                          : t('calendar.noProfitZone')}
                      </td>
                      <td className="align-right">
                        <span className={`score-badge ${c.score >= 70 ? 'high' : c.score >= 50 ? 'medium' : 'low'}`}>
                          {c.score.toFixed(0)}
                        </span>
                      </td>
                    </tr>
                    {expandedRow === idx && (
                      <tr key={`exp-${idx}`} style={{ background: '#f0f8ff' }}>
                        <td colSpan={10}>
                          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', padding: '8px 16px' }}>
                            <div>
                              <strong>{t('common.legDetails')}</strong>
                              <table style={{ fontSize: 13, marginTop: 4 }}>
                                <thead>
                                  <tr><th>{t('common.legDir')}</th><th>{t('common.legType')}</th><th>{t('common.legStrike')}</th><th>{t('common.legPrice')}</th><th>Delta</th><th>{t('common.legIv')}</th></tr>
                                </thead>
                                <tbody>
                                  {c.legs.map((l, i) => (
                                    <tr key={i}>
                                      <td>{l.side === 'buy' ? t('calendar.buyFar') : t('calendar.sellNear')}</td>
                                      <td>{l.kind}</td>
                                      <td>${formatNumber(l.strike, 0)}</td>
                                      <td>{l.price.toFixed(4)}</td>
                                      <td>{l.delta.toFixed(3)}</td>
                                      <td>{(l.iv * 100).toFixed(1)}%</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <div>
                              <strong>{t('common.greeksProfit')}</strong>
                              <div style={{ fontSize: 13, marginTop: 4 }}>
                                <div>{t('common.netVega')}: ${formatNumber(c.net_vega_usd, 2)}</div>
                                <div>{t('common.netTheta')}: ${formatNumber(c.net_theta_usd, 2)}/day</div>
                                <div>{t('calendar.ivSlopeRatio')}: {c.iv_slope_ratio.toFixed(3)}</div>
                                <div>{t('calendar.debitRatio')}: {c.debit_ratio.toFixed(2)}</div>
                                <div>{t('calendar.maxProfitEst')}: ${formatNumber(c.profit_zone.max_profit_est, 2)}</div>
                                <div>{t('calendar.optimalSpot')}: ${formatNumber(c.profit_zone.max_profit_spot, 0)}</div>
                                <div style={{ marginTop: 4 }}>{t('common.liquidityScore')}: {c.liquidity_score.toFixed(2)}</div>
                              </div>
                            </div>
                            <div style={{ flex: '1 1 320px', minWidth: 300 }}>
                              <PayoffChart
                                legs={c.legs}
                                spot={result.spot_price}
                                offsetYears={c.legs[0]?.t_years ?? 0}
                              />
                              <div style={{ marginTop: 12 }}>
                                <ScenarioTable legs={c.legs} spot={result.spot_price} />
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {result && result.candidates.length === 0 && (
        <div className="no-results">{t('common.noResults')}</div>
      )}
    </div>
  );
}
