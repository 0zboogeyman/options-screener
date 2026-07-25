import { useEffect, useState } from 'react';

/** 广告位组件：读 window.__SITE_CONFIG__.ads[id] 渲染广告。
 *
 *  两种形态（按配置自动判断）：
 *    1. 配置了 adsenseClient 且内容像 slot id（纯数字）→ AdSense <ins> + push
 *       （注意：dangerouslySetInnerHTML 注入的 <script> 不会执行，
 *        所以 AdSense 必须走这条组件内建路径，不能把整段代码贴进配置）
 *    2. 否则 → 内容视为 HTML 片段（直客图片/文字链广告）直接渲染
 *  内容为空 / 配置缺失 → 返回 null，不占页面空间。
 */

interface Props {
  id: string;
}

type AdContent =
  | { kind: 'adsense'; client: string; slot: string }
  | { kind: 'html'; html: string }
  | null;

export default function AdSlot({ id }: Props) {
  const [content, setContent] = useState<AdContent>(null);

  useEffect(() => {
    const cfg = (window as any).__SITE_CONFIG__;
    const raw: unknown = cfg?.ads?.[id];
    if (typeof raw !== 'string' || !raw.trim()) return;
    const val = raw.trim();
    const client: string = cfg.adsenseClient || '';
    if (client && /^\d+$/.test(val)) {
      setContent({ kind: 'adsense', client, slot: val });
    } else {
      setContent({ kind: 'html', html: val });
    }
  }, [id]);

  // AdSense：ins 渲染后通知 adsbygoogle 拉取广告
  useEffect(() => {
    if (content?.kind !== 'adsense') return;
    try {
      ((window as any).adsbygoogle = (window as any).adsbygoogle || []).push({});
    } catch {
      // adsbygoogle.js 尚未加载完成时静默忽略（罕见竞态，下条广告会正常）
    }
  }, [content]);

  if (!content) return null;

  if (content.kind === 'adsense') {
    return (
      <div className="ad-slot" style={{ margin: '16px auto', maxWidth: 728, textAlign: 'center' }}>
        <ins
          className="adsbygoogle"
          style={{ display: 'block' }}
          data-ad-client={content.client}
          data-ad-slot={content.slot}
          data-ad-format="auto"
          data-full-width-responsive="true"
        />
      </div>
    );
  }

  return (
    <div
      className="ad-slot"
      style={{ margin: '16px auto', maxWidth: 728, textAlign: 'center' }}
      dangerouslySetInnerHTML={{ __html: content.html }}
    />
  );
}
