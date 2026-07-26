import { useTranslation } from 'react-i18next';
import type { Bucket, ScanLeg } from '../types/api';
import { quarterKelly } from '../lib/kelly';

interface ResultBucketProps {
  bucket: Bucket;
  spotPrice: number;
}

export default function ResultBucket({ bucket, spotPrice }: ResultBucketProps) {
  const { t } = useTranslation();
  const legTypeLabel = bucket.leg_type === 'CALL' ? t('result.call') : t('result.put');
  const sideLabel = bucket.side === 'DEBIT' ? t('result.debit') : t('result.credit');
  const title = `${legTypeLabel} - ${sideLabel}`;
  const isDebit = bucket.side === 'DEBIT';
  const strategies = isDebit ? bucket.top.slice(0, 3) : bucket.bottom.slice(0, 3);
  const rankLabel = isDebit ? t('result.top3') : t('result.bottom3');
  const commentary = isDebit ? t('result.debitComment') : t('result.creditComment');

  const formatNumber = (num: number, decimals: number = 2): string => {
    return num.toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    });
  };

  const Row = ({ it }: { it: ScanLeg }) => {
    const premiumUsd = it.premium * spotPrice;
    const maxProfitUsd = isDebit ? it.max_profit : (it.max_profit * spotPrice);
    const maxLossUsd = isDebit ? (it.max_loss * spotPrice) : it.max_loss;
    const kelly = quarterKelly(it.pop, maxProfitUsd / Math.max(maxLossUsd, 1e-9));

    return (
      <tr>
        <td>{formatNumber(it.K1, 0)}</td>
        <td>{formatNumber(it.K2, 0)}</td>
        <td>{it.premium.toFixed(4)} (${formatNumber(premiumUsd, 2)})</td>
        <td>${formatNumber(maxProfitUsd, 2)}</td>
        <td>${formatNumber(maxLossUsd, 2)}</td>
        <td>{Number.isFinite(it.odds) ? it.odds.toFixed(1) : '—'}</td>
        <td style={{ fontWeight: 'bold', color: kelly.zero ? '#dc3545' : 'inherit' }}
          title={t('common.kellyTitle')}>{kelly.pct}</td>
      </tr>
    );
  };

  return (
    <div className="result-card">
      <div className="result-card-header">
        <h3>{title}</h3>
        <span className="badge">{rankLabel}</span>
      </div>
      <p className="result-card-description">{commentary}</p>
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('result.strike1')}</th>
              <th>{t('result.strike2')}</th>
              <th>{t('common.premium')} <span className="help-icon" title={t('common.premiumHelp')}>i</span></th>
              <th>{t('result.maxProfit')}</th>
              <th>{t('result.maxLoss')}</th>
              <th>{t('result.odds')}</th>
              <th>Kelly <span className="help-icon" title={t('common.kellyHelp')}>i</span></th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((it, idx) => <Row it={it} key={idx} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
