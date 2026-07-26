import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { DatesResp, ExpiriesResp, ScanResp, OpinionResult } from '../types/api';
import ResultBucket from '../components/ResultBucket';
import CSPScanner from '../components/CSPScanner';
import CCScanner from '../components/CCScanner';
import IronCondorScanner from '../components/IronCondorScanner';
import StrangleScanner from '../components/StrangleScanner';
import CalendarScanner from '../components/CalendarScanner';
import VolPanel from '../components/VolPanel';
import EtlRefreshButton from '../components/EtlRefreshButton';
import AdSlot from '../components/AdSlot';
import { useToast } from '../components/Toast';
import { usePersistedState } from '../lib/usePersistedState';
import i18n from '../lib/i18n';

const API_BASE = '/api';

/** 把 HTTP 错误状态转成可读文案（429 限流给出明确提示） */
function httpError(resp: Response, t: (k: string) => string): Error {
  if (resp.status === 429) return new Error(t('common.error429'));
  return new Error(`${resp.status} ${resp.statusText}`);
}

function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

function OpinionResultDisplay({ result, spotPrice }: { result: OpinionResult; spotPrice: number }) {
  const { t } = useTranslation();
  const items = result.items || [];
  const view = result.view;
  const side = result.side;
  const anchorLeg = result.anchor_leg;
  const anchorStrike = result.anchor_strike;
  const base = result.base || 'BTC';

  const strikeUnit = base === 'BTC' ? 1000 : 100;
  const strikeLabel = base === 'BTC' ? 'k' : '';

  const viewConfig: Record<string, { titleKey: string; descKey: string; ranking: string }> = {
    up: { titleKey: 'opinion.up.title', descKey: 'opinion.up.desc', ranking: 'Top' },
    down: { titleKey: 'opinion.down.title', descKey: 'opinion.down.desc', ranking: 'Top' },
    not_up: { titleKey: 'opinion.not_up.title', descKey: 'opinion.not_up.desc', ranking: 'Bottom' },
    not_down: { titleKey: 'opinion.not_down.title', descKey: 'opinion.not_down.desc', ranking: 'Bottom' }
  };

  const config = viewConfig[view] || viewConfig.up;
  const anchorLabel = t('opinion.anchorFixed', { leg: anchorLeg, strike: (anchorStrike / strikeUnit).toFixed(0), unit: strikeLabel });
  const rankingLabel = side === 'CREDIT' ? t('opinion.lowOdds') : t('opinion.highOdds');
  const ranking = config.ranking === 'Top' ? t('opinion.rankingTop') : t('opinion.rankingBottom');
  const subtitle = t('opinion.subtitle', {
    ranking,
    count: items.length,
    oddsLabel: rankingLabel,
    anchor: anchorLabel,
    desc: t(config.descKey)
  });
  const horizonKey = result.horizon === 'short' ? 'opinion.horizonShortLabel'
    : result.horizon === 'mid' ? 'opinion.horizonMidLabel' : 'opinion.horizonLongLabel';
  const horizonText = t(horizonKey);
  const sideText = side === 'CREDIT' ? t('opinion.descCredit') : t('opinion.descDebit');

  return (
    <div className="opinion-result">
      <div className="opinion-result-header">
        <h3>{t(config.titleKey)}</h3>
        <span className="opinion-result-subtitle">{subtitle}</span>
      </div>
      <p className="opinion-result-description">
        {t('opinion.desc', { horizon: horizonText, anchor: anchorLabel, side: sideText })}
        {result.notes?.strike_snapped ? t('opinion.strikeSnapped') : ''}
      </p>
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.expiry')}</th>
              <th>{t('opinion.k1')}</th>
              <th>{t('opinion.k2')}</th>
              <th>{t('common.premium')} <span className="help-icon" title={t('common.premiumHelp')}>i</span></th>
              <th>{t('opinion.maxProfit')}</th>
              <th>{t('opinion.maxLoss')}</th>
              <th>{t('opinion.odds')}</th>
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
        {side === 'DEBIT' ? t('opinion.debitFormula') : t('opinion.creditFormula')}
      </p>
    </div>
  );
}

function getDaysRemaining(expiryMs: number): number {
  const now = Date.now();
  const diff = expiryMs - now;
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function formatExpiry(expiryMs: number, t: (k: string, opts?: any) => string): string {
  if (expiryMs === 0) return t('expiry.perpetual');
  const date = new Date(expiryMs);
  const days = getDaysRemaining(expiryMs);
  // 保持 Deribit 结算时区（业务规则），仅日期格式化随语言切换
  const locale = i18n.language === 'en' ? 'en-US' : 'zh-CN';
  const dateStr = date.toLocaleDateString(locale, { month: '2-digit', day: '2-digit' });
  return t('expiry.expiryFormat', { date: dateStr, days });
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
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = usePersistedState<'opinion'|'expiry'|'csp'|'cc'|'ironcondor'|'strangle'|'calendar'|'vol'>('home.activeTab', 'opinion');
  const [dates, setDates] = useState<string[]>([]);
  const [base, setBase] = usePersistedState<'BTC'|'ETH'>('home.base', 'BTC');
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
    base?: 'BTC' | 'ETH';
  }>({});

  const [opinionHorizon, setOpinionHorizon] = usePersistedState<'short'|'mid'|'long'>('home.opinionHorizon', 'mid');
  const [opinionView, setOpinionView] = usePersistedState<'up'|'down'|'not_up'|'not_down'>('home.opinionView', 'up');
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
            base,
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

      if (!resp.ok) throw httpError(resp, t);

      const data = await resp.json() as ScanResp;

      setResult(data);
      setGlobalData({
        asof_ts: data.asof_ts,
        spot_price: data.spot_price || undefined,
        dvol_index: data.dvol_index || undefined,
        base,
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

  /** ETL 手动刷新完成后：重拉日期/元信息；同日更新（date 字符串不变）时手动重扫 */
  const handleEtlRefreshed = async () => {
    try {
      const datesResp = await fetch(`${API_BASE}/meta/dates`);
      const datesData: DatesResp = await datesResp.json();
      const ds = datesData.dates || [];
      setDates(ds);
      const latest = ds[ds.length - 1];
      if (!latest) return;
      const asofResp = await fetch(`${API_BASE}/meta/asof?base=${base}&date=${latest}`);
      if (asofResp.ok) {
        const asofData = await asofResp.json();
        setGlobalData({
          asof_ts: asofData.asof_ts,
          spot_price: asofData.spot_price ?? undefined,
          dvol_index: asofData.dvol_index ?? undefined,
          base,
        });
      }
      if (latest !== date) {
        setDate(latest);   // 触发 useEffect 链自动重扫
      } else if (activeTab === 'expiry' && selectedExpiry) {
        doScan();          // 同日更新：date 不变，手动重扫
      }
    } catch { /* 网络异常时静默——toast 已由按钮组件提示 */ }
  };

  const doOpinionScan = async () => {
    setLoading(true); setError(''); setOpinionResult(null);

    try {
      const targetValue = parseFloat(opinionTarget);
      if (isNaN(targetValue) || targetValue <= 0) {
        showToast(t('opinion.invalidTarget'), 'warning');
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

      if (!resp.ok) throw httpError(resp, t);
      const data: OpinionResult = await resp.json();
      setOpinionResult(data);
      setGlobalData({
        asof_ts: data.asof_ts,
        spot_price: data.spot_price || undefined,
        dvol_index: data.dvol_index || undefined,
        base,
      });
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally { setLoading(false); }
  };

  const targetUnit = base === 'BTC' ? t('opinion.targetUnitBtc') : t('opinion.targetUnitEth');
  const targetPlaceholder = base === 'BTC' ? t('opinion.placeholderBtc') : t('opinion.placeholderEth');
  // 保持 Deribit 结算时区（业务规则），仅 locale 随语言切换
  const bannerLocale = i18n.language === 'en' ? 'en-US' : 'zh-CN';

  return (
    <div className="app-container">
      <div className="header">
        <h1>{t('app.title')}</h1>
      </div>

      {globalData.asof_ts && (
        <div className="data-banner">
          <div className="data-banner-content">
            <div className="data-banner-item">
              <strong>{t('banner.dataTime')}</strong>
              <span className="value">{new Date(globalData.asof_ts).toLocaleString(bannerLocale, { timeZone: 'Asia/Shanghai', hour12: false })}</span>
            </div>
            {globalData.spot_price && (
              <div className="data-banner-item">
                <strong>{t('banner.spotPrice', { base: globalData.base || base })}</strong>
                <span className="value price">${formatNumber(globalData.spot_price, 2)}</span>
              </div>
            )}
            {globalData.dvol_index && (
              <div className="data-banner-item">
                <strong>{t('banner.dvolIndex')}</strong>
                <span className="value dvol">{globalData.dvol_index.toFixed(2)}%</span>
              </div>
            )}
            <EtlRefreshButton onRefreshed={handleEtlRefreshed} />
          </div>
        </div>
      )}

      <div className="tab-navigation">
        <button className={`tab-button ${activeTab === 'opinion' ? 'active' : ''}`} onClick={() => setActiveTab('opinion')}>
          <span className="tab-icon">📊</span>
          <span>{t('tabs.opinion')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'expiry' ? 'active' : ''}`} onClick={() => setActiveTab('expiry')}>
          <span className="tab-icon">📅</span>
          <span>{t('tabs.expiry')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'cc' ? 'active' : ''}`} onClick={() => setActiveTab('cc')}>
          <span className="tab-icon">📈</span>
          <span>{t('tabs.cc')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'csp' ? 'active' : ''}`} onClick={() => setActiveTab('csp')}>
          <span className="tab-icon">💰</span>
          <span>{t('tabs.csp')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'ironcondor' ? 'active' : ''}`} onClick={() => setActiveTab('ironcondor')}>
          <span className="tab-icon">🦅</span>
          <span>{t('tabs.ironcondor')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'strangle' ? 'active' : ''}`} onClick={() => setActiveTab('strangle')}>
          <span className="tab-icon">⚡</span>
          <span>{t('tabs.strangle')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'calendar' ? 'active' : ''}`} onClick={() => setActiveTab('calendar')}>
          <span className="tab-icon">📅</span>
          <span>{t('tabs.calendar')}</span>
        </button>
        <button className={`tab-button ${activeTab === 'vol' ? 'active' : ''}`} onClick={() => setActiveTab('vol')}>
          <span className="tab-icon">📉</span>
          <span>{t('tabs.vol')}</span>
        </button>
      </div>

      {activeTab === 'csp' ? (
        <CSPScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'cc' ? (
        <CCScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'ironcondor' ? (
        <IronCondorScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'strangle' ? (
        <StrangleScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'calendar' ? (
        <CalendarScanner onDataUpdate={setGlobalData} />
      ) : activeTab === 'vol' ? (
        <VolPanel />
      ) : activeTab === 'opinion' ? (
        <>
          <div className="filter-grid filter-grid-4">
            <label className="filter-label">
              <strong>{t('common.base')}</strong>
              <select className="filter-select" value={base} onChange={e => setBase(e.target.value as 'BTC'|'ETH')}>
                <option value="BTC">BTC</option>
                <option value="ETH">ETH</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>{t('opinion.horizon')}</strong>
              <select className="filter-select" value={opinionHorizon} onChange={e => setOpinionHorizon(e.target.value as any)}>
                <option value="short">{t('opinion.horizonShort')}</option>
                <option value="mid">{t('opinion.horizonMid')}</option>
                <option value="long">{t('opinion.horizonLong')}</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>{t('opinion.viewType')}</strong>
              <select className="filter-select" value={opinionView} onChange={e => setOpinionView(e.target.value as any)}>
                <option value="up">{t('opinion.viewUp')}</option>
                <option value="down">{t('opinion.viewDown')}</option>
                <option value="not_up">{t('opinion.viewNotUp')}</option>
                <option value="not_down">{t('opinion.viewNotDown')}</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>{t('opinion.targetPrice', { unit: targetUnit })}</strong>
              <input
                type="text"
                inputMode="decimal"
                className="filter-input"
                value={opinionTarget}
                onChange={e => setOpinionTarget(e.target.value)}
                placeholder={targetPlaceholder}
              />
            </label>
          </div>

          <button className="btn-primary" onClick={doOpinionScan}>{t('common.scan')}</button>

          {loading && <p className="loading-message">{t('common.analyzing')}</p>}
          {error && <p className="error-message">{error}</p>}

          {opinionResult && opinionResult.items && (
            <OpinionResultDisplay result={opinionResult} spotPrice={opinionResult.spot_price || 0} />
          )}
        </>
      ) : (
        <>
          <div className="filter-grid filter-grid-2">
            <label className="filter-label">
              <strong>{t('expiry.baseAsset')}</strong>
              <select className="filter-select" value={base} onChange={e => setBase(e.target.value as 'BTC'|'ETH')}>
                <option value="BTC">BTC</option>
                <option value="ETH">ETH</option>
              </select>
            </label>

            <label className="filter-label">
              <strong>{t('expiry.expiryDate')}</strong>
              <select
                className="filter-select"
                value={selectedExpiry}
                onChange={e => setSelectedExpiry(Number(e.target.value))}
              >
                {expiries.map(exp => (
                  <option key={exp} value={exp}>{formatExpiry(exp, t)}</option>
                ))}
              </select>
            </label>
          </div>

          {loading && <p className="loading-message">{t('common.analyzing')}</p>}
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

      <AdSlot id="ad-footer-top" />

      <div className="footer">
        <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '8px' }}>{t('footer.disclaimer')}</div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
          {t('footer.poweredBy')}
          <a href="https://github.com/0zBoogeyman/options-screener" target="_blank" rel="noopener noreferrer" aria-label="GitHub" style={{ display: 'inline-flex', alignItems: 'center', color: 'var(--primary-color)' }}>
            <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
            </svg>
          </a>
        </div>
      </div>
    </div>
  );
}
