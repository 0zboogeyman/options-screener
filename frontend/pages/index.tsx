import { useEffect, useState } from 'react';

import type { DatesResp, ExpiriesResp, ScanResp, OpinionResult } from '../types/api';
import ResultBucket from '../components/ResultBucket';
import CSPScanner from '../components/CSPScanner';
import CCScanner from '../components/CCScanner';
import { useToast } from '../components/Toast';

const API_BASE = '/api';

/** 把 HTTP 错误状态转成可读文案（429 限流给出明确提示） */
function httpError(resp: Response): Error {
  if (resp.status === 429) return new Error('操作太频繁，请稍候再试');
  return new Error(`${resp.status} ${resp.statusText}`);
}

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

function OpinionResultDisplay({ result, spotPrice }: { result: OpinionResult; spotPrice: number }) {
  const items = result.items || [];
  const view = result.view;
  const side = result.side;
  const anchorLeg = result.anchor_leg;
  const anchorStrike = result.anchor_strike;
  const base = result.base || 'BTC';

  const strikeUnit = base === 'BTC' ? 1000 : 100;
  const strikeLabel = base === 'BTC' ? 'k' : '';

  const viewConfig: Record<string, { title: string; description: string; ranking: string }> = {
    up: { title: '看涨期权 - 借方价差（付权利金）', description: '小成本博取大回报', ranking: 'Top' },
    down: { title: '看跌期权 - 借方价差（付权利金）', description: '趋势型看跌布局', ranking: 'Top' },
    not_up: { title: '看涨期权 - 贷方价差（收权利金）', description: '最具性价比的鸭子策略', ranking: 'Bottom' },
    not_down: { title: '看跌期权 - 贷方价差（收权利金）', description: '区间防守型策略', ranking: 'Bottom' }
  };

  const config = viewConfig[view] || viewConfig.up;
  const anchorLabel = `${anchorLeg} 固定：${(anchorStrike / strikeUnit).toFixed(0)}${strikeLabel}`;
  const rankingLabel = side === 'CREDIT' ? '（低赔率）' : '（高赔率）';
  const subtitle = `${config.ranking} ${items.length}${rankingLabel} · ${anchorLabel} · ${config.description}`;
  const horizonText = result.horizon === 'short' ? '≤1个月' : result.horizon === 'mid' ? '1-3个月' : '≥3个月';

  return (
    <div className="opinion-result">
      <div className="opinion-result-header">
        <h3>{config.title}</h3>
        <span className="opinion-result-subtitle">{subtitle}</span>
      </div>
      <p className="opinion-result-description">
        已筛选出 {horizonText} 内到期的期权链中，{anchorLabel} 时{side === 'CREDIT' ? '胜率最高' : '赔率最高'}的策略。
        {result.notes?.strike_snapped && ' （目标价已对齐至最近行权价）'}
      </p>
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>到期日</th>
              <th>K1</th>
              <th>K2</th>
              <th>权利金 <span className="help-icon" title="价格计算规则：&#10;1. 优先使用买卖价中间价 (bid+ask)/2&#10;2. 若无买卖价，使用 Deribit mark_price&#10;3. 若仍无数据，使用单边报价 bid 或 ask&#10;&#10;数据过滤规则：&#10;1. 过滤单腿期权 spread_ratio > 0.5（买卖价差超过中间价50%）&#10;2. 过滤组合权利金 < $10（避免深度虚值期权）">i</span></th>
              <th>最大利润</th>
              <th>最大亏损</th>
              <th>赔率</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s: any, idx: number) => {
              const premiumUsd = Math.abs(s.premium) * spotPrice;
              let maxProfitUsd: number;
              let maxLossUsd: number;
              if (side === 'DEBIT') {
                maxProfitUsd = s.max_profit;
                maxLossUsd = s.max_loss * spotPrice;
              } else {
                maxProfitUsd = s.max_profit * spotPrice;
                maxLossUsd = s.max_loss;
              }
              return (
                <tr key={idx}>
                  <td>{s.expiry_date}</td>
                  <td>{formatNumber(s.K1, 0)}</td>
                  <td>{formatNumber(s.K2, 0)}</td>
                  <td>{s.premium.toFixed(4)} (${formatNumber(premiumUsd, 2)})</td>
                  <td>${formatNumber(maxProfitUsd, 2)}</td>
                  <td>${formatNumber(maxLossUsd, 2)}</td>
                  <td>{s.odds.toFixed(1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="table-footer">
        {side === 'DEBIT'
          ? '借方价差：最大利润 = |K2 - K1| - 权利金；最大亏损 = 权利金'
          : '贷方价差：最大利润 = 权利金收入；最大亏损 = 价差 - 权利金'}
      </p>
    </div>
  );
}

function getDaysRemaining(expiryMs: number): number {
  const now = Date.now();
  const diff = expiryMs - now;
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function formatExpiry(expiryMs: number): string {
  if (expiryMs === 0) return '永续 (0天)';
  const date = new Date(expiryMs);
  const days = getDaysRemaining(expiryMs);
  const dateStr = date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  return `${dateStr} (${days}天)`;
}

function findWeeklyExpiry(expiries: number[]): number {
  const oneWeekLater = Date.now() + 7 * 24 * 60 * 60 * 1000;
  let closest = expiries[0];
  let minDiff = Math.abs(expiries[0] - oneWeekLater);
  for (const exp of expiries) {
    const diff = Math.abs(exp - oneWeekLater);
    if (diff < minDiff) {
      minDiff = diff;
      closest = exp;
    }
  }
  return closest;
}

export default function Home() {
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState<'opinion'|'expiry'|'csp'|'cc'>('opinion');
  const [dates, setDates] = useState<string[]>([]);
  const [base, setBase] = useState<'BTC'|'ETH'>('BTC');
  const [date, setDate] = useState<string>('');
  const [expiries, setExpiries] = useState<number[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanResp | null>(null);
  const [error, setError] = useState<string>('');

  const [globalData, setGlobalData] = useState<{
    asof_ts?: number;
    spot_price?: number;
    dvol_index?: number;
  }>({});

  const [opinionHorizon, setOpinionHorizon] = useState<'short'|'mid'|'long'>('mid');
  const [opinionView, setOpinionView] = useState<'up'|'down'|'not_up'|'not_down'>('up');
  const [opinionTarget, setOpinionTarget] = useState<string>('150');
  const [opinionResult, setOpinionResult] = useState<OpinionResult | null>(null);

  useEffect(() => {
    setOpinionTarget(base === 'BTC' ? '150' : '45');
  }, [base]);

  useEffect(() => {
    const ctrl = new AbortController();
    const fetchInitialData = async () => {
      try {
        const datesResp = await fetch(`${API_BASE}/meta/dates`, { signal: ctrl.signal });
        const datesData: DatesResp = await datesResp.json();
        const ds = datesData.dates || [];
        setDates(ds);
        if (ds.length === 0) return;

        const latestDate = ds[ds.length - 1];
        setDate(latestDate);

        // 仅取 asof/spot/dvol 元信息，不再触发一次完整扫描
        const asofResp = await fetch(`${API_BASE}/meta/asof?base=${base}&date=${latestDate}`, { signal: ctrl.signal });
        if (asofResp.ok) {
          const asofData = await asofResp.json();
          setGlobalData({
            asof_ts: asofData.asof_ts,
            spot_price: asofData.spot_price ?? undefined,
            dvol_index: asofData.dvol_index ?? undefined,
          });
        }
      } catch (e: any) {
        if (e?.name === 'AbortError') return;
        console.error('Failed to fetch initial data:', e);
      }
    };
    fetchInitialData();
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!date || !base) return;
    const ctrl = new AbortController();
    fetch(`${API_BASE}/expiries?base=${base}&date=${date}`, { signal: ctrl.signal })
      .then(r => r.json())
      .then((d: ExpiriesResp) => {
        const exps = d.expiries.filter((e: number) => e !== 0);
        setExpiries(exps);
        if (exps.length > 0) {
          setSelectedExpiry(findWeeklyExpiry(exps));
        }
      })
      .catch((e: Error) => { if (e?.name !== 'AbortError') setError(String(e)); });
    return () => ctrl.abort();
  }, [date, base]);

  const doScan = async (signal?: AbortSignal) => {
    if (!selectedExpiry) return;
    setLoading(true); setError(''); setResult(null);

    const days = getDaysRemaining(selectedExpiry);
    let tenor: 'near' | 'mid' | 'far' = 'near';
    if (days > 60) tenor = 'far';
    else if (days > 30) tenor = 'mid';

    try {
      // direction=both 一次请求返回 CALL+PUT 全部 bucket，
      // 替代原先 up/down 两次请求 + 前端合并
      const resp = await fetch(`${API_BASE}/spread/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal,
        body: JSON.stringify({ base, date, direction: 'both', tenor, return_per_bucket: 10 })
      });

      if (!resp.ok) throw httpError(resp);

      const data = await resp.json() as ScanResp;

      setResult(data);
      setGlobalData({
        asof_ts: data.asof_ts,
        spot_price: data.spot_price || undefined,
        dvol_index: data.dvol_index || undefined,
      });
    } catch (e: any) {
      if (e?.name === 'AbortError') return;
      setError(e?.message || String(e));
    } finally { if (!signal?.aborted) setLoading(false); }
  };

  useEffect(() => {
    if (!date || !selectedExpiry) return;
    const ctrl = new AbortController();
    doScan(ctrl.signal);
    return () => ctrl.abort();
  }, [date, base, selectedExpiry]);

  const doOpinionScan = async () => {
    setLoading(true); setError(''); setOpinionResult(null);

    try {
      const targetValue = parseFloat(opinionTarget);
      if (isNaN(targetValue) || targetValue <= 0) {
        showToast('请输入有效的目标价格', 'warning');
        return;
      }

      const multiplier = base === 'BTC' ? 1000 : 100;
      const targetPriceUsd = targetValue * multiplier;

      const resp = await fetch(`${API_BASE}/spread/opinion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base, horizon: opinionHorizon, view: opinionView,
          target_price: targetPriceUsd, max_gap_steps: 8, return_per_bucket: 3
        })
      });

      if (!resp.ok) throw httpError(resp);
      const data: OpinionResult = await resp.json();
      setOpinionResult(data);
      setGlobalData({
        asof_ts: data.asof_ts,
        spot_price: data.spot_price || undefined,
        dvol_index: data.dvol_index || undefined,
      });
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setLoading(false); }
  };

  return (
    <div className="app-container">
      <div className="header">
        <h1>期权策略推荐</h1>
      </div>

      {globalData.asof_ts && (
        <div className="data-banner">
          <div className="data-banner-content">
            <div className="data-banner-item">
              <strong>数据时间</strong>
              <span className="value">{new Date(globalData.asof_ts).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</span>
            </div>
            {globalData.spot_price && (
              <div className="data-banner-item">
                <strong>现货价格 ({base})</strong>
                <span className="value price">${formatNumber(globalData.spot_price, 2)}</span>
              </div>
            )}
            {globalData.dvol_index && (
              <div className="data-banner-item">
                <strong>DVOL 指数</strong>
                <span className="value dvol">{globalData.dvol_index.toFixed(2)}%</span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="tab-navigation">
        <button className={`tab-button ${activeTab === 'opinion' ? 'active' : ''}`} onClick={() => setActiveTab('opinion')}>
          <span className="tab-icon">📊</span>
          <span>观点</span>
        </button>
        <button className={`tab-button ${activeTab === 'expiry' ? 'active' : ''}`} onClick={() => setActiveTab('expiry')}>
          <span className="tab-icon">📅</span>
          <span>到期</span>
        </button>
        <button className={`tab-button ${activeTab === 'cc' ? 'active' : ''}`} onClick={() => setActiveTab('cc')}>
          <span className="tab-icon">📈</span>
          <span>卖币</span>
        </button>
        <button className={`tab-button ${activeTab === 'csp' ? 'active' : ''}`} onClick={() => setActiveTab('csp')}>
          <span className="tab-icon">💰</span>
          <span>买币</span>
        </button>
      </div>

      {activeTab === 'csp' ? (
        <CSPScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'cc' ? (
        <CCScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'opinion' ? (
        <>
          <div className="filter-grid filter-grid-4">
            <label className="filter-label">
              <strong>标的</strong>
              <select className="filter-select" value={base} onChange={e => setBase(e.target.value as 'BTC'|'ETH')}>
                <option value="BTC">BTC</option>
                <option value="ETH">ETH</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>时间期限</strong>
              <select className="filter-select" value={opinionHorizon} onChange={e => setOpinionHorizon(e.target.value as any)}>
                <option value="short">短期 (≤1月)</option>
                <option value="mid">中期 (1-3月)</option>
                <option value="long">长期 (≥3月)</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>观点类型</strong>
              <select className="filter-select" value={opinionView} onChange={e => setOpinionView(e.target.value as any)}>
                <option value="up">会上涨到 ≥</option>
                <option value="down">会下跌到 ≤</option>
                <option value="not_up">不会上涨到 ≥</option>
                <option value="not_down">不会下跌到 ≤</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>目标价（{base === 'BTC' ? '千美元' : '百美元'}）</strong>
              <input
                type="text"
                inputMode="decimal"
                className="filter-input"
                value={opinionTarget}
                onChange={e => setOpinionTarget(e.target.value)}
                placeholder={base === 'BTC' ? '例如: 135' : '例如: 55'}
              />
            </label>
          </div>

          <button className="btn-primary" onClick={doOpinionScan}>扫描策略</button>

          {loading && <p className="loading-message">正在分析...</p>}
          {error && <p className="error-message">{error}</p>}

          {opinionResult && opinionResult.items && (
            <OpinionResultDisplay result={opinionResult} spotPrice={opinionResult.spot_price || 0} />
          )}
        </>
      ) : (
        <>
          <div className="filter-grid filter-grid-2">
            <label className="filter-label">
              <strong>标的资产</strong>
              <select className="filter-select" value={base} onChange={e => setBase(e.target.value as 'BTC'|'ETH')}>
                <option value="BTC">BTC</option>
                <option value="ETH">ETH</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>到期日</strong>
              <select
                className="filter-select"
                value={selectedExpiry}
                onChange={e => setSelectedExpiry(Number(e.target.value))}
              >
                {expiries.map(exp => (
                  <option key={exp} value={exp}>{formatExpiry(exp)}</option>
                ))}
              </select>
            </label>
          </div>

          {loading && <p className="loading-message">正在分析...</p>}
          {error && <p className="error-message">{error}</p>}

          {result && result.spot_price && (
            <div>
              {result.buckets.map((b, idx) => (
                <ResultBucket key={idx} bucket={b} spotPrice={result.spot_price || 0} />
              ))}
            </div>
          )}
        </>
      )}

      <div className="footer">
        <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '8px' }}>仅教育用途，非投资建议，数据来源于 Deribit</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          Powered by
          <a href="https://github.com/0zboogeyman/option-strategy-finder" target="_blank" rel="noopener noreferrer" aria-label="GitHub" style={{ display: 'inline-flex', alignItems: 'center', color: 'var(--primary-color)' }}>
            <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
            </svg>
          </a>
        </div>
      </div>
    </div>
  );
}
