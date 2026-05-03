export default function AsOfBadge({ date }: { date?: string | null }) {
  if (!date) return null;
  return (
    <div style={{ background: '#f2f2f2', display: 'inline-block', padding: '4px 8px', borderRadius: 6, margin: '8px 0' }}>
      数据日期：{date}
    </div>
  );
}

