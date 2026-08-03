"""波动率历史存储与指标计算。

存储（独立于 dt=* 分区，不受 backup_retention_days 清理影响）：
  * vol/history.parquet      — 每日每到期切片的 SVI 拟合结果（ETL 追加）
  * vol/dvol_history.parquet — DVOL 日频蜡烛（backfill_dvol.py 回填 + ETL 日更）

指标：
  * 30d 固定期限 ATM IV：同一日期各切片总方差在目标期限上线性插值
  * IVP（IV Percentile）：当前值在过去 N 天中的百分位
  * IVR（IV Rank）：(current − min) / (max − min)
  * skew 分位数：rr25 的历史百分位（数据随 ETL 累积）

所有 append 幂等：按业务主键去重保留最后一条；写入先 tmp 后 rename。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.config import settings

logger = logging.getLogger(__name__)

VOL_DIR: Path = settings.data_root / "vol"
HISTORY_PATH: Path = VOL_DIR / "history.parquet"
DVOL_PATH: Path = VOL_DIR / "dvol_history.parquet"

# IVP/IVR 默认回看窗口（天）
DEFAULT_LOOKBACK_DAYS = 365
# IVR 最小有效天数：低于此值时 IVR 无统计意义（冷启动期），返回 None
IVR_MIN_DAYS = 30
# 固定期限插值目标（天）
DEFAULT_TARGET_DTE = 30.0

SVI_DEDUPE_KEYS = ["date", "base", "expiry_ts"]
DVOL_DEDUPE_KEYS = ["base", "ts"]


class _FileLock:
    """<path>.lock 上的排他文件锁（阻塞获取，失败抛 OSError）。

    与 etl_daily._EtlLock 同款的 fcntl/msvcrt 双实现，区别是这里写路径
    极短（毫秒级），阻塞等待比非阻塞拒绝更省心。防止多进程并发 append
    同一 parquet 时读改写丢数据。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(self._path, "a+")
        if os.name == "nt":
            import msvcrt

            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)  # 重试约 10s 后抛 OSError
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fd.seek(0)
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            self._fd.close()
            self._fd = None

    def __enter__(self) -> "_FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def append_rows(rows: List[Dict], path: Path, dedupe_keys: List[str]) -> int:
    """追加行到 parquet（不存在则新建），按 dedupe_keys 去重保留最后一条。

    返回写入后的总行数。
    """
    new_df = pd.DataFrame(rows)
    lock_path = path.with_suffix(".parquet.lock")
    with _FileLock(lock_path):
        if path.exists():
            old_df = pd.read_parquet(path)
            df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            df = new_df
        df = df.drop_duplicates(subset=dedupe_keys, keep="last").reset_index(drop=True)
        _atomic_write_parquet(df, path)
    logger.info("vol_history appended %d rows -> %s (total=%d)", len(new_df), path, len(df))
    return len(df)


def append_svi_rows(rows: List[Dict], path: Path = HISTORY_PATH) -> int:
    return append_rows(rows, path, SVI_DEDUPE_KEYS)


def append_dvol_rows(rows: List[Dict], path: Path = DVOL_PATH) -> int:
    return append_rows(rows, path, DVOL_DEDUPE_KEYS)


def load_svi_history(base: Optional[str] = None, path: Path = HISTORY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if base is not None and not df.empty:
        df = df[df["base"] == base]
    return df.reset_index(drop=True)


def load_dvol_history(base: Optional[str] = None, path: Path = DVOL_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    mtime = path.stat().st_mtime
    cache_key = str(path)
    with _DVOL_CACHE_LOCK:
        cached = _DVOL_CACHE.get(cache_key)
        if cached is not None and cached[0] == mtime:
            df = cached[1]
        else:
            df = pd.read_parquet(path)
            if len(_DVOL_CACHE) >= _DVOL_CACHE_MAX:
                _DVOL_CACHE.pop(next(iter(_DVOL_CACHE)))
            _DVOL_CACHE[cache_key] = (mtime, df)
    if base is not None and not df.empty:
        df = df[df["base"] == base]
    return df.sort_values("ts").reset_index(drop=True)


def fixed_tenor_iv(
    day_slices: pd.DataFrame,
    target_dte: float = DEFAULT_TARGET_DTE,
) -> Optional[float]:
    """由单日全部切片的 (dte, atm_iv) 插值出固定期限（默认 30d）ATM IV。

    在总方差 w = iv²·T 上对期限线性插值（标准做法），只接受 ok 切片。
    覆盖不了目标期限时用最近切片（dte 需 ≥ 7 天），无可用数据返回 None。
    """
    df = day_slices
    df = df[(df["quality"] == "ok") & df["atm_iv"].notna() & (df["dte"] > 0)]
    if df.empty:
        return None
    df = df.sort_values("dte")

    t_target = target_dte / 365.0
    dtes = df["dte"].to_numpy(dtype=float)
    ivs = df["atm_iv"].to_numpy(dtype=float)
    ws = ivs ** 2 * (dtes / 365.0)

    below = df[df["dte"] <= target_dte]
    above = df[df["dte"] >= target_dte]
    if not below.empty and not above.empty:
        lo = below.iloc[-1]
        hi = above.iloc[0]
        t_lo, t_hi = lo["dte"] / 365.0, hi["dte"] / 365.0
        w_lo, w_hi = lo["atm_iv"] ** 2 * t_lo, hi["atm_iv"] ** 2 * t_hi
        if t_hi == t_lo:
            w_t = w_lo
        else:
            frac = (t_target - t_lo) / (t_hi - t_lo)
            w_t = w_lo + frac * (w_hi - w_lo)
        return float(np.sqrt(max(w_t, 1e-12) / t_target))

    # 目标期限在曲面之外：取 dte 最近且 ≥7 天的切片
    df = df[df["dte"] >= 7]
    if df.empty:
        return None
    idx = int(np.argmin(np.abs(df["dte"].to_numpy(dtype=float) - target_dte)))
    return float(df["atm_iv"].iloc[idx])


def ivp_ivr(
    history: pd.Series,
    current: float,
    lookback: int = DEFAULT_LOOKBACK_DAYS,
) -> Dict:
    """IV 百分位与 IV Rank。

    history: 按时间升序的日频 IV 序列（单位与 current 一致即可）。
    current: 当前 IV。返回 {ivp, ivr, days_available}；样本 <2 时 ivp/ivr 为 None。
    """
    vals = pd.to_numeric(history, errors="coerce").dropna().to_numpy(dtype=float)
    vals = vals[-lookback:] if len(vals) > lookback else vals
    days = int(len(vals))
    if days < 2 or not np.isfinite(current):
        return {"ivp": None, "ivr": None, "days_available": days}
    ivp = float(np.mean(vals <= current))
    vmin, vmax = float(np.min(vals)), float(np.max(vals))
    # IVR 需要足够长的历史窗口才有统计意义；冷启动期（days < IVR_MIN_DAYS）
    # 或无波动范围（vmax == vmin）时返回 None，前端显示 "—" 而非误导性的 0%
    ivr = None if (vmax == vmin or days < IVR_MIN_DAYS) else float((current - vmin) / (vmax - vmin))
    return {"ivp": ivp, "ivr": ivr, "days_available": days}


def percentile_rank(history: pd.Series, current: float, lookback: int = DEFAULT_LOOKBACK_DAYS) -> Dict:
    """任意序列的百分位（用于 rr25 skew 等）。语义同 ivp_ivr 的 ivp 字段。"""
    vals = pd.to_numeric(history, errors="coerce").dropna().to_numpy(dtype=float)
    vals = vals[-lookback:] if len(vals) > lookback else vals
    days = int(len(vals))
    if days < 2 or not np.isfinite(current):
        return {"percentile": None, "days_available": days}
    return {"percentile": float(np.mean(vals <= current)), "days_available": days}


# ---------------------------------------------------------------------------
# SVI surface / 当前 IV 状态（供扫描器使用）
# ---------------------------------------------------------------------------

_SURFACE_CACHE: Dict = {}
_SURFACE_CACHE_MAX = 8
_SURFACE_CACHE_LOCK = threading.Lock()
_DVOL_CACHE: Dict[str, tuple[float, pd.DataFrame]] = {}
_DVOL_CACHE_MAX = 4
_DVOL_CACHE_LOCK = threading.Lock()


def load_svi_surface(date: str, base: str, path: Path = HISTORY_PATH) -> Dict[int, Dict]:
    """加载某日某币种全部 ok 切片的 SVI 参数，key=expiry_ts。

    返回 {expiry_ts: {a,b,rho,m,sigma,atm_iv,rr25,bf25,dte}}。
    带 mtime 缓存：文件不变时不重复读盘（扫描路径高频调用）。
    """
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    key = (date, base, mtime, str(path))
    with _SURFACE_CACHE_LOCK:
        if key in _SURFACE_CACHE:
            return _SURFACE_CACHE[key]

    df = pd.read_parquet(path)
    df = df[(df["date"] == date) & (df["base"] == base) & (df["quality"] == "ok")]
    cols = ["a", "b", "rho", "m", "sigma", "atm_iv", "rr25", "bf25", "dte"]
    out: Dict[int, Dict] = {
        int(k): v for k, v in df.set_index("expiry_ts")[cols].to_dict("index").items()
    }
    with _SURFACE_CACHE_LOCK:
        if len(_SURFACE_CACHE) >= _SURFACE_CACHE_MAX:
            _SURFACE_CACHE.pop(next(iter(_SURFACE_CACHE)))
        _SURFACE_CACHE[key] = out
    return out


def current_iv_metrics(base: str, dvol_path: Path = DVOL_PATH) -> Dict:
    """当前波动率状态：DVOL 水平 + IVP/IVR（冷启动期由 DVOL 序列支撑）。

    返回 {dvol, ivp, ivr, days_available}；无数据时全 None。
    """
    df = load_dvol_history(base, path=dvol_path)
    if df.empty:
        return {"dvol": None, "ivp": None, "ivr": None, "days_available": 0}
    cur = float(df["close"].iloc[-1])
    out = ivp_ivr(df["close"], cur)
    return {"dvol": cur, **out}
