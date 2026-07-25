import { useState } from 'react';

import type { StrangleResult } from '../types/api';
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

export default function StrangleScanner({ onDataUpdate }: Props) {
  const [base, setBase] = usePersistedState<'BTC' | 'ETH'>('st.base', 'BTC');
  const [side, setSide] = usePersistedState<'both' | 'long' | 'short'>('st.side', 'both');
  const [dteMin, setDteMin] = usePersistedState('st.dteMin', '7');
  const [dteMax, setDteMax] = usePersistedState('st.dteMax', '45');
  const [deltaMin, setDeltaMin] = usePersistedState('st.deltaMin', '0.10');
  const [deltaMax, setDeltaMax] = usePersistedState('st.deltaMax', '0.30');
  const [minOi, setMinOi] = usePersistedState('st.minOi', '10');
  const [pricingMode, setPricingMode] = usePersistedState<'mid' | 'conservative'>('st.pricingMode', 'mid');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<StrangleResult | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const handleScan = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/strategy/strangle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base,
          side,
          dte_min: parseInt(dteMin),
          dte_max: parseInt(dteMax),
          delta_min: parseFloat(deltaMin),
          delta_max: parseFloat(deltaMax),
          min_oi: parseInt(minOi),
          pricing_mode: pricingMode,
          return_count: 15,
        })
      });

      if (!resp.ok) {
        if (resp.status === 429) throw new Error('操作太频繁，请稍候再试');
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: StrangleResult = await resp.json();
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
      <h2 className="scanner-title">宽跨式（Strangle）</h2>
      <p className="scanner-description">
        策略说明：同到期 OTM Put + OTM Call 组合。做多波动率（买入）赌大行情，做空波动率（卖出）赌区间震荡
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
          <strong>方向</strong>
          <select className="filter-select" value={side} onChange={e => setSide(e.target.value as any)}>
            <option value="both">做多 + 做空</option>
            <option value="long">仅做多波动</option>
            <option value="short">仅做空波动</option>
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
          <strong>Delta 下限</strong>
          <input type="number" step="0.01" className="filter-input" value={deltaMin} onChange={e => setDeltaMin(e.target.value)} />
        </label>
        <label className="filter-label">
          <strong>Delta 上限</strong>
          <input type="number" step="0.01" className="filter-input" value={deltaMax} onChange={e => setDeltaMax(e.target.value)} />
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

      {result && (result.long.length > 0 || result.short.length > 0) && (
        <div>
          {result.long.length > 0 && (
            <div className="result-card" style={{ marginBottom: 16 }}>
              <h3 style={{ padding: '12px 16px', margin: 0, color: '#28a745' }}>
                做多波动（Long Strangle）— {result.long.length} 个策略
              </h3>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>到期日</th>
                      <th className="align-right">DTE</th>
                      <th className="align-right">Put / Call 行权价</th>
                      <th className="align-right">成本</th>
                      <th className="align-right">盈亏区间</th>
                      <th className="align-right">需波动%</th>
                      <th className="align-right">获利概率</th>
                      <th className="align-right">成本/波动比</th>
                      <th className="align-right">Vega/$</th>
                      <th className="align-right">得分</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.long.map((c, idx) => (
                      <>
                        <tr
                          key={`l-${idx}`}
                          onClick={() => setExpandedRow(expandedRow === `l-${idx}` ? null : `l-${idx}`)}
                          style={{
                            background: expandedRow === `l-${idx}` ? '#f0f8ff' : idx % 2 === 0 ? '#fff' : '#fafafa',
                            cursor: 'pointer'
                          }}
                        >
                          <td>{c.expiry_date}</td>
                          <td className="align-right">{c.dte}</td>
                          <td className="align-right" style={{ fontSize: 12 }}>
                            {formatNumber(c.strikes[0], 0)} / {formatNumber(c.strikes[1], 0)}
                          </td>
                          <td className="align-right" style={{ color: '#dc3545' }}>${formatNumber(c.cost_usd, 2)}</td>
                          <td className="align-right" style={{ fontSize: 12 }}>
                            {formatNumber(c.breakeven_lo, 0)} ~ {formatNumber(c.breakeven_hi, 0)}
                          </td>
                          <td className="align-right">{(c.move_required_pct * 100).toFixed(1)}%</td>
                          <td className="align-right">{(c.pop_profit * 100).toFixed(1)}%</td>
                          <td className="align-right">{c.cost_ratio.toFixed(2)}</td>
                          <td className="align-right">{c.vega_per_dollar.toFixed(4)}</td>
                          <td className="align-right">
                            <span className={`score-badge ${c.score >= 70 ? 'high' : c.score >= 50 ? 'medium' : 'low'}`}>
                              {c.score.toFixed(0)}
                            </span>
                          </td>
                        </tr>
                        {expandedRow === `l-${idx}` && (
                          <tr key={`l-exp-${idx}`} style={{ background: '#f0f8ff' }}>
                            <td colSpan={10}>
                              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', padding: '8px 16px' }}>
                                <div>
                                  <strong>腿详情</strong>
                                  <table style={{ fontSize: 13, marginTop: 4 }}>
                                    <thead>
                                      <tr><th>方向</th><th>类型</th><th>行权价</th><th>价格</th><th>Delta</th><th>IV</th></tr>
                                    </thead>
                                    <tbody>
                                      {c.legs.map((l, i) => (
                                        <tr key={i}>
                                          <td>买入</td>
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
                                  <strong>Greeks</strong>
                                  <div style={{ fontSize: 13, marginTop: 4 }}>
                                    <div>净 Delta: {c.greeks.net_delta.toFixed(3)}</div>
                                    <div>净 Vega: ${formatNumber(c.greeks.net_vega_usd, 2)}</div>
                                    <div>净 Theta: ${formatNumber(c.greeks.net_theta_usd, 2)}/day</div>
                                    <div style={{ marginTop: 4 }}>流动性评分: {c.liquidity_score.toFixed(2)}</div>
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

          {result.short.length > 0 && (
            <div className="result-card">
              <h3 style={{ padding: '12px 16px', margin: 0, color: '#dc3545' }}>
                做空波动（Short Strangle）— {result.short.length} 个策略
                <span style={{ fontSize: 12, fontWeight: 'normal', marginLeft: 8, color: '#856404' }}>
                  ⚠️ 理论亏损无限，尾部为 RND 5% 期望亏损估计
                </span>
              </h3>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>到期日</th>
                      <th className="align-right">DTE</th>
                      <th className="align-right">Put / Call 行权价</th>
                      <th className="align-right">权利金收入</th>
                      <th className="align-right">盈亏区间</th>
                      <th className="align-right">胜率</th>
                      <th className="align-right">APR(保证金)</th>
                      <th className="align-right">尾部亏损估计</th>
                      <th className="align-right">保证金</th>
                      <th className="align-right">
                        Kelly <span className="help-icon" title="简化 Kelly 仓位建议：f* = p − q/b，显示 1/4 Kelly。&#10;p=胜率（RND），b=权利金/尾部亏损估计（RND 5% ES）。&#10;仅供参考，非投资建议。">i</span>
                      </th>
                      <th className="align-right">得分</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.short.map((c, idx) => (
                      <>
                        <tr
                          key={`s-${idx}`}
                          onClick={() => setExpandedRow(expandedRow === `s-${idx}` ? null : `s-${idx}`)}
                          style={{
                            background: expandedRow === `s-${idx}` ? '#f0f8ff' : idx % 2 === 0 ? '#fff' : '#fafafa',
                            cursor: 'pointer'
                          }}
                        >
                          <td>{c.expiry_date}</td>
                          <td className="align-right">{c.dte}</td>
                          <td className="align-right" style={{ fontSize: 12 }}>
                            {formatNumber(c.strikes[0], 0)} / {formatNumber(c.strikes[1], 0)}
                          </td>
                          <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                            ${formatNumber(c.credit_usd, 2)}
                          </td>
                          <td className="align-right" style={{ fontSize: 12 }}>
                            {formatNumber(c.breakeven_lo, 0)} ~ {formatNumber(c.breakeven_hi, 0)}
                          </td>
                          <td className="align-right">{(c.pop * 100).toFixed(1)}%</td>
                          <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                            {c.apr_on_im != null ? `${(c.apr_on_im * 100).toFixed(1)}%` : '—'}
                          </td>
                          <td className="align-right" style={{ color: '#dc3545' }}>
                            ${formatNumber(c.tail_loss_est_usd, 0)}
                          </td>
                          <td className="align-right">${formatNumber(c.im_standard_usd, 0)}</td>
                          <td className="align-right" style={{ fontWeight: 'bold', color: quarterKelly(c.pop, c.credit_usd / c.tail_loss_est_usd).zero ? '#dc3545' : 'inherit' }}
                            title="1/4 Kelly 建议仓位（占可用保证金）">
                            {quarterKelly(c.pop, c.credit_usd / c.tail_loss_est_usd).pct}
                          </td>
                          <td className="align-right">
                            <span className={`score-badge ${c.score >= 70 ? 'high' : c.score >= 50 ? 'medium' : 'low'}`}>
                              {c.score.toFixed(0)}
                            </span>
                          </td>
                        </tr>
                        {expandedRow === `s-${idx}` && (
                          <tr key={`s-exp-${idx}`} style={{ background: '#f0f8ff' }}>
                            <td colSpan={11}>
                              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', padding: '8px 16px' }}>
                                <div>
                                  <strong>腿详情</strong>
                                  <table style={{ fontSize: 13, marginTop: 4 }}>
                                    <thead>
                                      <tr><th>方向</th><th>类型</th><th>行权价</th><th>价格</th><th>Delta</th><th>IV</th></tr>
                                    </thead>
                                    <tbody>
                                      {c.legs.map((l, i) => (
                                        <tr key={i}>
                                          <td>卖出</td>
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
                                  <strong>Greeks & 风险</strong>
                                  <div style={{ fontSize: 13, marginTop: 4 }}>
                                    <div>净 Delta: {c.greeks.net_delta.toFixed(3)}</div>
                                    <div>净 Vega: ${formatNumber(c.greeks.net_vega_usd, 2)}</div>
                                    <div>净 Theta: ${formatNumber(c.greeks.net_theta_usd, 2)}/day</div>
                                    <div style={{ marginTop: 4, color: '#856404' }}>{c.risk_warning}</div>
                                    <div>流动性评分: {c.liquidity_score.toFixed(2)}</div>
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
        </div>
      )}

      {result && result.long.length === 0 && result.short.length === 0 && (
        <div className="no-results">未找到符合条件的策略，请调整筛选条件</div>
      )}
    </div>
  );
}
