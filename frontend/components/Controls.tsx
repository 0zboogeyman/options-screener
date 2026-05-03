type Props = {
  base: 'BTC'|'ETH';
  date: string;
  dates: string[];
  direction: 'up'|'down';
  tenor: 'near'|'mid'|'far';
  onChangeBase: (v: 'BTC'|'ETH') => void;
  onChangeDate: (v: string) => void;
  onChangeDirection: (v: 'up'|'down') => void;
  onChangeTenor: (v: 'near'|'mid'|'far') => void;
}

export default function Controls({ base, date, dates, direction, tenor, onChangeBase, onChangeDate, onChangeDirection, onChangeTenor }: Props) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, margin: '12px 0' }}>
      <label>
        Base
        <select value={base} onChange={e => onChangeBase(e.target.value as 'BTC'|'ETH')} style={{ width: '100%' }}>
          <option value="BTC">BTC</option>
          <option value="ETH">ETH</option>
        </select>
      </label>
      <label>
        Date
        <select value={date} onChange={e => onChangeDate(e.target.value)} style={{ width: '100%' }}>
          {dates.map((d) => <option value={d} key={d}>{d}</option>)}
        </select>
      </label>
      <label>
        Direction
        <select value={direction} onChange={e => onChangeDirection(e.target.value as 'up'|'down')} style={{ width: '100%' }}>
          <option value="up">上涨</option>
          <option value="down">下跌</option>
        </select>
      </label>
      <label>
        Tenor
        <select value={tenor} onChange={e => onChangeTenor(e.target.value as 'near'|'mid'|'far')} style={{ width: '100%' }}>
          <option value="near">近月</option>
          <option value="mid">中期</option>
          <option value="far">远期</option>
        </select>
      </label>
    </div>
  );
}

