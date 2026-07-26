import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { VolPanelData } from '../types/api';
import { usePersistedState } from '../lib/usePersistedState';

const API_BASE = '/api';

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

/** IVP/IVR 颜色：高 IV 用红色（贵），低 IV 用绿色（便宜） */
function ivColor(ivp: number | null): string {
  if (ivp == null) return '#666';
  if (ivp >= 0.7) return '#dc3545';
  if (ivp <= 0.3) return '#28a745';
  return '#856404';
}

export default function VolPanel() {
  const { t } = useTranslation();
  const [base, setBase] = usePersistedState<'BTC' | 'ETH'>('vol.base', 'BTC');
  const [data, setData] = useState<VolPanelData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/meta/vol?base=${base}`, { signal: ctrl.signal })
      .then(r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: VolPanelData) => setData(d))
      .catch(e => { if (e?.name !== 'AbortError') setError(e?.message || String(e)); })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [base]);

  // DVOL 趋势迷你图（SVG sparkline）
  const dvolSparkline = (() => {
    if (!data || data.dvol_history.length < 2) return null;
    const points = data.dvol_history.filter(d => d.close != null);
    if (points.length < 2) return null;
    const vals = points.map(d => d.close!);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const w = 300;
    const h = 60;
    const step = w / (points.length - 1);
    const path = points.map((d, i) => {
      const x = i * step;
      const y = h - ((d.close! - min) / range) * h;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const lastVal = vals[vals.length - 1];
    const firstVal = vals[0];
    const isUp = lastVal >= firstVal;
    return (
      <svg width={w} height={h} style={{ display: 'block' }}>
        <path d={path} fill="none" stroke={isUp ? '#dc3545' : '#28a745'} strokeWidth={1.5} />
        <circle cx={w} cy={h - ((lastVal - min) / range) * h} r={2.5} fill={isUp ? '#dc3545' : '#28a745'} />
      </svg>
    );
  })();

  return (
    <div className="scanner-section">
      <h2 className="scanner-title">{t('vol.title')}</h2>
      <p className="scanner-description">
        {t('vol.description')}
      </p>

      <div className="filter-grid filter-grid-2" style={{ marginBottom: 16 }}>
        <label className="filter-label">
          <strong>{t('common.base')}</strong>
          <select className="filter-select" value={base} onChange={e => setBase(e.target.value as any)}>
            <option value="BTC">BTC</option>
            <option value="ETH">ETH</option>
          </select>
        </label>
      </div>

      {loading && <p className="loading-message">{t('common.loading')}</p>}
      {error && <div className="error-message">{error}</div>}

      {data && (
        <div>
          {/* 指标卡片 */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
            <div style={{
              background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8,
              padding: '16px 24px', minWidth: 140
            }}>
              <div style={{ fontSize: 13, color: '#666' }}>{t('vol.dvolIndex')}</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: '#333' }}>
                {data.dvol != null ? `${data.dvol.toFixed(1)}%` : '—'}
              </div>
            </div>
            <div style={{
              background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8,
              padding: '16px 24px', minWidth: 140
            }}>
              <div style={{ fontSize: 13, color: '#666' }}>{t('vol.ivp')}</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: ivColor(data.ivp) }}>
                {data.ivp != null ? `${(data.ivp * 100).toFixed(0)}%` : '—'}
              </div>
              <div style={{ fontSize: 11, color: '#999' }}>{t('vol.daysSample', { count: data.days_available })}</div>
            </div>
            <div style={{
              background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8,
              padding: '16px 24px', minWidth: 140
            }}>
              <div style={{ fontSize: 13, color: '#666' }}>{t('vol.ivr')}</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: ivColor(data.ivr) }}>
                {data.ivr != null ? `${(data.ivr * 100).toFixed(0)}%` : '—'}
              </div>
            </div>
            {dvolSparkline && (
              <div style={{
                background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8,
                padding: '8px 16px', minWidth: 320
              }}>
                <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{t('vol.dvolTrend')}</div>
                {dvolSparkline}
              </div>
            )}
          </div>

          {/* 期限结构表 */}
          {data.term_structure.length > 0 && (
            <div className="result-card">
              <h3 style={{ padding: '12px 16px', margin: 0 }}>{t('vol.termTitle')}</h3>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t('common.expiry')}</th>
                      <th className="align-right">{t('common.dte')}</th>
                      <th className="align-right">{t('vol.atmIv')}</th>
                      <th className="align-right">{t('vol.rr25')}</th>
                      <th className="align-right">{t('vol.bf25')}</th>
                      <th className="align-right">{t('vol.skewJudge')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.term_structure.map((t_row, idx) => (
                      <tr key={idx} style={{ background: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
                        <td>{t_row.expiry_date}</td>
                        <td className="align-right">{t_row.dte}</td>
                        <td className="align-right" style={{ fontWeight: 'bold' }}>
                          {t_row.atm_iv != null ? `${t_row.atm_iv.toFixed(1)}%` : '—'}
                        </td>
                        <td className="align-right" style={{
                          color: t_row.rr25 != null && t_row.rr25 < -1 ? '#dc3545' : t_row.rr25 != null && t_row.rr25 > 1 ? '#28a745' : '#666'
                        }}>
                          {t_row.rr25 != null ? `${t_row.rr25.toFixed(2)}%` : '—'}
                        </td>
                        <td className="align-right">
                          {t_row.bf25 != null ? `${t_row.bf25.toFixed(2)}%` : '—'}
                        </td>
                        <td className="align-right" style={{ fontSize: 12 }}>
                          {t_row.rr25 != null
                            ? t_row.rr25 < -1 ? t('vol.putRich')
                              : t_row.rr25 > 1 ? t('vol.callRich')
                              : t('vol.symmetric')
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 12, color: '#999', padding: '0 16px 12px' }}>
                {t('vol.rr25Note')}
              </p>
            </div>
          )}

          {data.term_structure.length === 0 && (
            <div className="no-results">{t('vol.noData')}</div>
          )}
        </div>
      )}
    </div>
  );
}
