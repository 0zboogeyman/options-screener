import { useState } from 'react';

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
  onDataUpdate?: (data: { asof_ts: number; spot_price?: number; dvol_index?: number }) => void;
}

export default function IronCondorScanner({ onDataUpdate }: Props) {
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
        if (resp.status === 429) throw new Error('操作太频繁，请稍候再试');
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: IronCondorResult = await resp.json();
      setResult(data);

      if (onDataUpdate && data.asof_ts) {
        onDataUpdate({
          asof_ts: data.asof_ts,
          spot_price: data.spot_price,
          dvol_index: data.dvol_index,
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
      <h2 className="scanner-title">铁秃鹰（Iron Condor）</h2>
      <p className="scanner-description">
        策略说明：同一到期卖 OTM Put 价差 + 卖 OTM Call 价差，四腿组合——价格在区间内白收权利金，两端有保护腿限制亏损
      </p>

      <div className="filter-grid filter-grid-3">
        <label className="filter-label">
          <strong>标的</strong>
          <select className="filter-select" value={base} onChange={e => setBase(e.target.value as any)}>
            <option value="BTC">BTC</option>
            <option value="ETH">ETH</option>
          </select>
        </label>
        <label className="filter-label">
          <strong>DTE 最小（天）</strong>
          <input type="number" className="filter-input" value={dteMin} onChange={e => setDteMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>DTE 最大（天）</strong>
          <input type="number" className="filter-input" value={dteMax} onChange={e => setDteMax(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>短腿 Delta 下限</strong>
          <input type="number" step="0.01" className="filter-input" value={shortDeltaMin} onChange={e => setShortDeltaMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>短腿 Delta 上限</strong>
          <input type="number" step="0.01" className="filter-input" value={shortDeltaMax} onChange={e => setShortDeltaMax(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>最小持仓量</strong>
          <input type="number" className="filter-input" value={minOi} onChange={e => setMinOi(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>定价模式</strong>
          <select className="filter-select" value={pricingMode} onChange={e => setPricingMode(e.target.value as any)}>
            <option value="mid">中间价</option>
            <option value="conservative">保守价（可执行）</option>
          </select>
        </label>
      </div>

      <button className="btn-primary" onClick={handleScan} disabled={loading}>
        {loading ? '扫描中...' : '扫描策略'}
      </button>

      {error && <div className="error-message">{error}</div>}

      {result && result.candidates.length > 0 && (
        <div className="result-card">
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>到期日</th>
                  <th className="align-right">DTE</th>
                  <th className="align-right">行权价</th>
                  <th className="align-right">权利金收入</th>
                  <th className="align-right">最大亏损</th>
                  <th className="align-right">盈亏区间</th>
                  <th className="align-right">胜率</th>
                  <th className="align-right">APR</th>
                  <th className="align-right">保证金</th>
                  <th className="align-right">
                    Kelly <span className="help-icon" title="简化 Kelly 仓位建议：f* = p − q/b，显示 1/4 Kelly。&#10;p=胜率（RND），b=权利金/最大亏损。&#10;仅供参考，非投资建议。">i</span>
                  </th>
                  <th className="align-right">得分</th>
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
                        title="1/4 Kelly 建议仓位（占可用保证金）">
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
                              <strong>腿详情</strong>
                              <table style={{ fontSize: 13, marginTop: 4 }}>
                                <thead>
                                  <tr><th>方向</th><th>类型</th><th>行权价</th><th>价格</th><th>Delta</th><th>IV</th><th>OI</th></tr>
                                </thead>
                                <tbody>
                                  {c.legs.map((l, i) => (
                                    <tr key={i}>
                                      <td>{l.side === 'buy' ? '买入' : '卖出'}</td>
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
                              <strong>Greeks</strong>
                              <div style={{ fontSize: 13, marginTop: 4 }}>
                                <div>净 Delta: {c.greeks.net_delta.toFixed(3)}</div>
                                <div>净 Vega: ${formatNumber(c.greeks.net_vega_usd, 2)}</div>
                                <div>净 Theta: ${formatNumber(c.greeks.net_theta_usd, 2)}/day</div>
                                <div style={{ marginTop: 4 }}>IVP 评分: {c.ivp_score ? (c.ivp_score * 100).toFixed(0) : '—'}</div>
                                <div>流动性评分: {c.liquidity_score.toFixed(2)}</div>
                                <div>ROI: {(c.roi_on_max_loss * 100).toFixed(1)}%</div>
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
        <div className="no-results">未找到符合条件的策略，请调整筛选条件</div>
      )}
    </div>
  );
}
