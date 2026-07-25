import { useState } from 'react';

import type { CCResult } from '../types/api';
import { usePersistedState } from '../lib/usePersistedState';

const API_BASE = '/api';

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

interface CCScannerProps {
  onDataUpdate?: (data: { asof_ts: number; spot_price?: number; dvol_index?: number }) => void;
}

export default function CCScanner({ onDataUpdate }: CCScannerProps) {
  const [base, setBase] = usePersistedState<'BTC'|'ETH'>('cc.base', 'BTC');
  const [maxDte, setMaxDte] = usePersistedState('cc.maxDte', '60');
  const [maxDelta, setMaxDelta] = usePersistedState('cc.maxDelta', '0.30');
  const [minOi, setMinOi] = usePersistedState('cc.minOi', '10');
  const [maxSpreadBps, setMaxSpreadBps] = usePersistedState('cc.maxSpreadBps', '1500');
  const [positionSize, setPositionSize] = usePersistedState('cc.positionSize', '1');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CCResult | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const handleScan = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const resp = await fetch(`${API_BASE}/strategy/cc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base,
          max_dte: parseInt(maxDte),
          max_delta: parseFloat(maxDelta),
          min_oi: parseInt(minOi),
          max_spread_bps: parseInt(maxSpreadBps),
          position_size: parseInt(positionSize),
          return_count: 20
        })
      });

      if (!resp.ok) {
        if (resp.status === 429) throw new Error('操作太频繁，请稍候再试');
        throw new Error(`${resp.status} ${resp.statusText}`);
      }
      const data: CCResult = await resp.json();
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
      <h2 className="scanner-title">高抛收租（备兑卖 Call · CC）</h2>
      <p className="scanner-description">策略说明：持币备兑卖出看涨期权（Call）——涨至目标价则按溢价出货，没涨到则白收权利金</p>

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
          <strong>持仓合约数量（张）</strong>
          <input type="number" className="filter-input" value={positionSize} onChange={e => setPositionSize(e.target.value)} />
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
                  <th className="align-right">上涨空间%</th>
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
                    <td className="align-right">{(c.upside_pct * 100).toFixed(2)}%</td>
                    <td className="align-right" style={{ color: '#28a745', fontWeight: 'bold' }}>
                      {(c.apr_notional * 100).toFixed(1)}%
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
