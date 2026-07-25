import { useEffect, useState } from 'react';

/** localStorage 持久化的 useState（key 前缀 pref:）。
 *
 *  防 hydration mismatch：静态导出页面 SSG HTML 用的是 initial，
 *  若 lazy initializer 直接读 localStorage，客户端首渲染与 SSG 不一致
 *  会报 hydration 错误。所以首渲染始终用 initial，挂载后 useEffect
 *  再读存储值（会有一次视觉闪动，但无报错、无状态撕裂）。
 */
export function usePersistedState<T>(
  key: string,
  initial: T,
): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(initial);
  const [loaded, setLoaded] = useState(false);

  // 挂载后读取存储值
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`pref:${key}`);
      if (raw != null) setValue(JSON.parse(raw));
    } catch { /* 损坏数据回退默认值 */ }
    setLoaded(true);
  }, [key]);

  // 仅在完成初次加载后回写，避免用默认值覆盖存储
  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(`pref:${key}`, JSON.stringify(value));
    } catch { /* 隐私模式等写失败静默 */ }
  }, [key, value, loaded]);

  return [value, setValue];
}
