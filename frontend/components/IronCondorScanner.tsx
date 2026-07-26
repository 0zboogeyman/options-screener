import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { IronCondorResult } from '../types/api';
import PayoffChart from './PayoffChart';
import ScenarioTable from './ScenarioTable';
import { quarterKelly } from '../lib/kelly';
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

export default function IronCondorScanner({ onDataUpdate }: Props) {
  const { t } = useTranslation();
  const [base, setBase] = usePersistedState<'BTC' | 'ETH'>('ic.base', 'BTC');
  const [dteMin, setDteMin] = usePersistedState('ic.dteMin', '14');
  const [dteMax, setDteMax] = usePersistedState('ic.dteMax', '60');
  const [shortDeltaMin, setShortDeltaMin] = usePersistedState('ic.shortDeltaMin', '0.10');
  const [shortDeltaMax, setShortDeltaMax] = usePersistedState('ic.shortDeltaMax', '0.25');
  const [minOi, setMinOi] = usePersistedState('ic.minOi', '10');
  const [pricingMode, setPricingMode] = usePersistedState<'mid' | 'conservative'>('ic.pricingMode', 'mid');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<IronCondorResult | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const handleScan = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/strategy/iron-condor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base,
          dte_min: parseInt(dteMin),
          dte_max: parseInt(dteMax),
          short_delta_min: parseFloat(shortDeltaMin),
          short_delta_max: parseFloat(shortDeltaMax),
          min_oi: parseInt(minOi),
          pricing_mode: pricingMode,
          return_count: 20,
        })
      });

      if (!resp.ok) {
        if (resp.status === 429) throw new Error(t('common.error429'));
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: IronCondorResult = await resp.json();
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
      <h2 className="scanner-title">{t('ironcondor.title')}</h2>
      <p className="scanner-description">
        {t('ironcondor.description')}
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
          <strong>{t('common.dteMin')}</strong>
          <input type="number" className="filter-input" value={dteMin} onChange={e => setDteMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('common.dteMax')}</strong>
          <input type="number" className="filter-input" value={dteMax} onChange={e => setDteMax(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('ironcondor.shortDeltaMin')}</strong>
          <input type="number" step="0.01" className="filter-input" value={shortDeltaMin} onChange={e => setShortDeltaMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>{t('ironcondor.shortDeltaMax')}</strong>
          <input type="number" step="0.01" className="filter-input" value={shortDeltaMax} onChange={e => setShortDeltaMax(e.target.value)} />
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
                  <th>{t('common.expiry')}</th>
                  <th className="align-right">{t('common.dte')}</th>
                  <th className="align-right">{t('common.strikes')}</th>
                  <th className="align-right">{t('ironcondor.credit')}</th>
                  <th className="align-right">{t('ironcondor.maxLoss')}</th>
                  <th className="align-right">{t('ironcondor.range')}</th>
                  <th className="align-right">{t('ironcondor.winRate')}</th>
                  <th className="align-right">{t('ironcondor.apr')}</th>
                  <th className="align-right">{t('ironcondor.margin')}</th>
                  <th className="align-right">
                    Kelly <span className="help-icon" title={t('common.kellyHelp')}>i</span>
                  </th>
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
                      <td>{c.expiry_date}</td>
                      <td className="align-right">{c.dte}</td>
                      <td className="align-right" style={{ fontSize: 12 }}>
                        {c.strikes.map(k => formatNumber(k, 0)).join(' / ')}
                      </td>
                      <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                        ${formatNumber(c.credit_usd, 2)}
                      </td>
                      <td className="align-right" style={{ color: '#dc3545' }}>
                        ${formatNumber(c.max_loss_usd, 2)}
                      </td>
                      <td className="align-right" style={{ fontSize: 12 }}>
                        {formatNumber(c.breakeven_lo, 0)} ~ {formatNumber(c.breakeven_hi, 0)}
                      </td>
                      <td className="align-right">{(c.pop * 100).toFixed(1)}%</td>
                      <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                        {(c.apr_on_max_loss * 100).toFixed(1)}%
                      </td>
                      <td className="align-right">${formatNumber(c.im_standard_usd, 0)}</td>
                      <td className="align-right" style={{ fontWeight: 'bold', color: quarterKelly(c.pop, c.credit_usd / c.max_loss_usd).zero ? '#dc3545' : 'inherit' }}
                        title={t('common.kellyTitle')}>
                        {quarterKelly(c.pop, c.credit_usd / c.max_loss_usd).pct}
                      </td>
                      <td className="align-right">
                        <span className={`score-badge ${c.score >= 70 ? 'high' : c.score >= 50 ? 'medium' : 'low'}`}>
                          {c.score.toFixed(0)}
                        </span>
                      </td>
                    </tr>
                    {expandedRow === idx && (
                      <tr key={`exp-${idx}`} style={{ background: '#f0f8ff' }}>
                        <td colSpan={11}>
                          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', padding: '8px 16px' }}>
                            <div>
                              <strong>{t('common.legDetails')}</strong>
                              <table style={{ fontSize: 13, marginTop: 4 }}>
                                <thead>
                                  <tr><th>{t('common.legDir')}</th><th>{t('common.legType')}</th><th>{t('common.legStrike')}</th><th>{t('common.legPrice')}</th><th>Delta</th><th>{t('common.legIv')}</th><th>{t('common.legOi')}</th></tr>
                                </thead>
                                <tbody>
                                  {c.legs.map((l, i) => (
                                    <tr key={i}>
                                      <td>{l.side === 'buy' ? t('common.buy') : t('common.sell')}</td>
                                      <td>{l.kind}</td>
                                      <td>${formatNumber(l.strike, 0)}</td>
                                      <td>{l.price.toFixed(4)}</td>
                                      <td>{l.delta.toFixed(3)}</td>
                                      <td>{(l.iv * 100).toFixed(1)}%</td>
                                      <td>{formatNumber(l.oi, 0)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <div>
                              <strong>{t('common.greeks')}</strong>
                              <div style={{ fontSize: 13, marginTop: 4 }}>
                                <div>{t('common.netDelta')}: {c.greeks.net_delta.toFixed(3)}</div>
                                <div>{t('common.netVega')}: ${formatNumber(c.greeks.net_vega_usd, 2)}</div>
                                <div>{t('common.netTheta')}: ${formatNumber(c.greeks.net_theta_usd, 2)}/day</div>
                                <div style={{ marginTop: 4 }}>{t('common.ivpScore')}: {c.ivp_score ? (c.ivp_score * 100).toFixed(0) : '—'}</div>
                                <div>{t('common.liquidityScore')}: {c.liquidity_score.toFixed(2)}</div>
                                <div>{t('ironcondor.roi')}: {(c.roi_on_max_loss * 100).toFixed(1)}%</div>
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
