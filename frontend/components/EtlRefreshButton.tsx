import { useEffect, useState } from 'react';

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
  const [token, setToken] = useState('');
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setToken(resolveAdminToken());
  }, []);

  // 轮询运行状态直到结束
  useEffect(() => {
    if (!running || !token) return;
    const timer = setInterval(async () => {
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
            showToast(`数据更新失败：${s.last_error}`, 'error');
          } else {
            showToast('数据已更新', 'success');
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
        showToast('管理口令无效，请通过 ?admin=口令 重新进入', 'error');
        localStorage.removeItem(TOKEN_KEY);
        setToken('');
        return;
      }
      if (resp.status === 409) {
        showToast('已有更新任务在运行中', 'warning');
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
      {running ? '更新中…（约1-3分钟）' : '更新数据'}
    </button>
  );
}
