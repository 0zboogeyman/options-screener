type ScanLeg = {
  K1: number; K2: number; premium: number; max_profit: number; max_loss: number; odds: number; pop?: number | null; quality?: string | null;
}
type Bucket = { leg_type: 'CALL'|'PUT'; side: 'DEBIT'|'CREDIT'; top: ScanLeg[]; bottom: ScanLeg[] };

interface ResultBucketProps {
  bucket: Bucket;
  spotPrice: number;
}

function getStrategyTitle(legType: string, side: string): string {
  const typeMap: Record<string, string> = {
    'CALL': '看涨期权',
    'PUT': '看跌期权'
  };
  const sideMap: Record<string, string> = {
    'DEBIT': '借方价差 (付权利金)',
    'CREDIT': '贷方价差 (收权利金)'
  };
  return `${typeMap[legType] || legType} - ${sideMap[side] || side}`;
}

export default function ResultBucket({ bucket, spotPrice }: ResultBucketProps) {
  const title = getStrategyTitle(bucket.leg_type, bucket.side);
  const isDebit = bucket.side === 'DEBIT';
  const strategies = isDebit ? bucket.top.slice(0, 3) : bucket.bottom.slice(0, 3);
  const rankLabel = isDebit ? 'Top 3（高赔率）' : 'Bottom 3（低赔率）';
  const commentary = isDebit ? '小成本博取大回报' : '最具性价比的鸭子策略';

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

    return (
      <tr>
        <td>{formatNumber(it.K1, 0)}</td>
        <td>{formatNumber(it.K2, 0)}</td>
        <td>{it.premium.toFixed(4)} (${formatNumber(premiumUsd, 2)})</td>
        <td>${formatNumber(maxProfitUsd, 2)}</td>
        <td>${formatNumber(maxLossUsd, 2)}</td>
        <td>{Number.isFinite(it.odds) ? it.odds.toFixed(1) : '—'}</td>
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
              <th>执行价1</th>
              <th>执行价2</th>
              <th>权利金 <span className="help-icon" title="价格计算规则：&#10;1. 优先使用买卖价中间价 (bid+ask)/2&#10;2. 若无买卖价，使用 Deribit mark_price&#10;3. 若仍无数据，使用单边报价 bid 或 ask&#10;&#10;数据过滤规则：&#10;1. 过滤单腿期权 spread_ratio > 0.5（买卖价差超过中间价50%）&#10;2. 过滤组合权利金 < $10（避免深度虚值期权）">i</span></th>
              <th>最大收益</th>
              <th>最大亏损</th>
              <th>赔率</th>
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
