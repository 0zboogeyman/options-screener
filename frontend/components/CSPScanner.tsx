import { useState } from 'react';

import type { CSPResult } from '../types/api';

const API_BASE = '/api';

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

interface CSPScannerProps {
  onDataUpdate?: (data: { asof_ts: number; spot_price?: number; dvol_index?: number }) => void;
}

export default function CSPScanner({ onDataUpdate }: CSPScannerProps) {
  const [base, setBase] = useState<'BTC'|'ETH'>('BTC');
  const [maxDte, setMaxDte] = useState('60');
  const [maxDelta, setMaxDelta] = useState('0.30');
  const [minOi, setMinOi] = useState('10');
  const [maxSpreadBps, setMaxSpreadBps] = useState('1500');
  const [availableCash, setAvailableCash] = useState('120000');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CSPResult | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const handleScan = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/strategy/csp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base,
          max_dte: parseInt(maxDte),
          max_delta: parseFloat(maxDelta),
          min_oi: parseInt(minOi),
          max_spread_bps: parseInt(maxSpreadBps),
          available_cash: parseFloat(availableCash),
          return_count: 20
        })
      });

      if (!resp.ok) {
        if (resp.status === 429) throw new Error('操作太频繁，请稍候再试');
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: CSPResult = await resp.json();
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
      <h2 className="scanner-title">CSP - 打折买币</h2>
      <p className="scanner-description">策略说明：卖出看跌期权（Put），目标以折扣价格接货或赚取权利金</p>

      <div className="filter-grid filter-grid-3">
        <label className="filter-label">
          <strong>标的</strong>
          <select className="filter-select" value={base} onChange={e => setBase(e.target.value as any)}>
            <option value="BTC">BTC</option>
            <option value="ETH">ETH</option>
          </select>
        </label>

        <label className="filter-label">
          <strong>最大DTE（天）</strong>
          <input type="number" className="filter-input" value={maxDte} onChange={e => setMaxDte(e.target.value)} />
        </label>

        <label className="filter-label">
          <strong>最大Delta</strong>
          <input type="number" step="0.01" className="filter-input" value={maxDelta} onChange={e => setMaxDelta(e.target.value)} />
        </label>

        <label className="filter-label">
          <strong>可用保证金（USD）</strong>
          <input type="number" className="filter-input" value={availableCash} onChange={e => setAvailableCash(e.target.value)} />
        </label>

        <label className="filter-label">
          <strong>最小持仓量</strong>
          <input type="number" className="filter-input" value={minOi} onChange={e => setMinOi(e.target.value)} />
        </label>

        <label className="filter-label">
          <strong>最大点差（bps）</strong>
          <input type="number" className="filter-input" value={maxSpreadBps} onChange={e => setMaxSpreadBps(e.target.value)} />
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
                  <th>合约</th>
                  <th>到期日</th>
                  <th className="align-right">行权价</th>
                  <th className="align-right">Delta</th>
                  <th className="align-right">权利金</th>
                  <th className="align-right">盈亏平衡</th>
                  <th className="align-right">折扣%</th>
                  <th className="align-right">APR</th>
                  <th className="align-right">行权概率</th>
                  <th className="align-right">持仓量</th>
                  <th className="align-right">得分</th>
                </tr>
              </thead>
              <tbody>
                {result.candidates.map((c, idx) => (
                  <tr
                    key={idx}
                    onClick={() => setExpandedRow(expandedRow === idx ? null : idx)}
                    style={{
                      background: expandedRow === idx ? '#f0f8ff' : idx % 2 === 0 ? '#fff' : '#fafafa'
                    }}
                  >
                    <td style={{ fontSize: 12 }}>{c.symbol}</td>
                    <td>{c.expiry_date}</td>
                    <td className="align-right">${formatNumber(c.strike, 0)}</td>
                    <td className="align-right">{c.delta.toFixed(2)}</td>
                    <td className="align-right">${formatNumber(c.premium, 2)}</td>
                    <td className="align-right">${formatNumber(c.breakeven, 2)}</td>
                    <td className="align-right">{(c.discount_pct * 100).toFixed(2)}%</td>
                    <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                      {(c.apr * 100).toFixed(1)}%
                    </td>
                    <td className="align-right">{(c.assign_prob * 100).toFixed(1)}%</td>
                    <td className="align-right">{formatNumber(c.oi, 0)}</td>
                    <td className="align-right">
                      <span className={`score-badge ${c.score >= 70 ? 'high' : c.score >= 50 ? 'medium' : 'low'}`}>
                        {c.score.toFixed(0)}
                      </span>
                    </td>
                  </tr>
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
