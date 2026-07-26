import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Trans } from 'react-i18next';

const ACK_KEY = 'disclaimer_ack';
const AUTO_DISMISS_SEC = 3;

/** 首访免责声明确认弹窗。sessionStorage 记住已读；
 *  显示 AUTO_DISMISS_SEC 秒后自动关闭（也可手动点击提前关闭）。 */
export default function DisclaimerModal() {
  const { t } = useTranslation();
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
        <h2 style={{ margin: '0 0 12px', fontSize: 17 }}>{t('disclaimer.title')}</h2>
        <div style={{ fontSize: 13, lineHeight: 1.8, color: '#444' }}>
          <p style={{ margin: '0 0 8px' }}><Trans i18nKey="disclaimer.p1" components={{ strong: <strong /> }} /></p>
          <p style={{ margin: '0 0 8px' }}><Trans i18nKey="disclaimer.p2" components={{ strong: <strong /> }} /></p>
          <p style={{ margin: '0 0 8px' }}>{t('disclaimer.p3')}</p>
          <p style={{ margin: 0 }}>{t('disclaimer.p4')}</p>
        </div>
        <button
          onClick={ack}
          className="btn-primary"
          style={{ marginTop: 16, width: '100%' }}
        >
          {t('disclaimer.button', { count: countdown })}
        </button>
      </div>
    </div>
  );
}
