import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useToast } from './Toast';

const API_BASE = '/api';
const TOKEN_KEY = 'admin_token';

/** 从 URL ?admin=xxx 提取口令存入 localStorage（仅首次），返回当前口令 */
function resolveAdminToken(): string {
  if (typeof window === 'undefined') return '';
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get('admin');
  if (fromUrl) {
    localStorage.setItem(TOKEN_KEY, fromUrl);
    params.delete('admin');
    const qs = params.toString();
    const clean = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
    window.history.replaceState(null, '', clean);
    return fromUrl;
  }
  return localStorage.getItem(TOKEN_KEY) || '';
}

interface Props {
  onRefreshed?: () => void;
}

export default function EtlRefreshButton({ onRefreshed }: Props) {
  const { showToast } = useToast();
  const { t } = useTranslation();
  const [token, setToken] = useState('');
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setToken(resolveAdminToken());
  }, []);

  // 轮询运行状态直到结束（审计 P3-8：加最大轮询次数，防 ETL 卡死无限轮询）
  useEffect(() => {
    if (!running || !token) return;
    let polls = 0;
    const MAX_POLLS = 60;   // 60 × 3s = 3 分钟上限
    const timer = setInterval(async () => {
      polls += 1;
      if (polls > MAX_POLLS) {
        clearInterval(timer);
        setRunning(false);
        showToast(t('etl.timeout'), 'error');
        return;
      }
      try {
        const resp = await fetch(`${API_BASE}/etl/status`, {
          headers: { 'X-Admin-Token': token },
        });
        if (!resp.ok) return;
        const s = await resp.json();
        if (!s.running) {
          clearInterval(timer);
          setRunning(false);
          if (s.last_error) {
            showToast(t('etl.failed', { error: s.last_error }), 'error');
          } else {
            showToast(t('etl.success'), 'success');
            onRefreshed?.();
          }
        }
      } catch {
        // 网络抖动时继续轮询，不中断
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [running, token]);

  const handleClick = async () => {
    try {
      const resp = await fetch(`${API_BASE}/etl/run`, {
        method: 'POST',
        headers: { 'X-Admin-Token': token },
      });
      if (resp.status === 401) {
        showToast(t('etl.invalidToken'), 'error');
        localStorage.removeItem(TOKEN_KEY);
        setToken('');
        return;
      }
      if (resp.status === 409) {
        showToast(t('etl.conflict'), 'warning');
        setRunning(true);  // 接上现有任务的轮询
        return;
      }
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      setRunning(true);
    } catch (e: any) {
      showToast(e?.message || String(e), 'error');
    }
  };

  // 无口令（访客视角）：不渲染按钮，纯查看版
  if (!token) return null;

  return (
    <button
      onClick={handleClick}
      disabled={running}
      style={{
        marginLeft: 'auto',
        padding: '6px 14px',
        fontSize: 13,
        border: '1px solid var(--primary-color, #185FA5)',
        borderRadius: 6,
        background: running ? '#e9ecef' : 'transparent',
        color: running ? '#999' : 'var(--primary-color, #185FA5)',
        cursor: running ? 'not-allowed' : 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      {running ? t('etl.running') : t('etl.refresh')}
    </button>
  );
}
