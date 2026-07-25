import { useEffect, useState } from 'react';

const ACK_KEY = 'disclaimer_ack';
const AUTO_DISMISS_SEC = 3;

/** 首访免责声明确认弹窗。sessionStorage 记住已读；
 *  显示 AUTO_DISMISS_SEC 秒后自动关闭（也可手动点击提前关闭）。 */
export default function DisclaimerModal() {
  const [visible, setVisible] = useState(false);
  const [countdown, setCountdown] = useState(AUTO_DISMISS_SEC);

  useEffect(() => {
    try {
      if (!sessionStorage.getItem(ACK_KEY)) setVisible(true);
    } catch {
      setVisible(true);  // 隐私模式等场景：保守起见每次显示
    }
  }, []);

  const ack = () => {
    try { sessionStorage.setItem(ACK_KEY, '1'); } catch { /* ignore */ }
    setVisible(false);
  };

  // 倒计时自动关闭
  useEffect(() => {
    if (!visible) return;
    if (countdown <= 0) { ack(); return; }
    const t = setTimeout(() => setCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [visible, countdown]);

  if (!visible) return null;

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 16,
    }}>
      <div style={{
        background: '#fff', borderRadius: 10, maxWidth: 520, width: '100%',
        padding: '24px 28px', boxShadow: '0 8px 30px rgba(0,0,0,0.2)',
      }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 17 }}>风险提示与免责声明</h2>
        <div style={{ fontSize: 13, lineHeight: 1.8, color: '#444' }}>
          <p style={{ margin: '0 0 8px' }}>本工具展示的所有策略扫描结果、胜率估计（PoP）、Kelly 仓位建议与保证金估算，<strong>仅供教育与研究参考，不构成任何投资建议</strong>。</p>
          <p style={{ margin: '0 0 8px' }}>期权交易存在高风险，可能导致全部本金损失；卖出期权（尤其是裸卖宽跨等无保护策略）理论亏损可能<strong>超过本金</strong>。</p>
          <p style={{ margin: '0 0 8px' }}>数据来源于 Deribit 公开 API，可能存在延迟或错误；概率模型基于隐含波动率假设，不代表未来实际结果。</p>
          <p style={{ margin: 0 }}>使用本工具即表示您理解并自行承担所有交易盈亏。</p>
        </div>
        <button
          onClick={ack}
          className="btn-primary"
          style={{ marginTop: 16, width: '100%' }}
        >
          我已理解并同意（{countdown}s 后自动关闭）
        </button>
      </div>
    </div>
  );
}
