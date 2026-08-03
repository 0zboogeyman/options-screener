#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import httpx
import numpy as np
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.svi import fit_svi_slice
from app.services.vol_history import append_svi_rows

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

DATA_ROOT: Path = settings.data_root
DERIBIT: str = settings.deribit_api_url


# ---------------------------------------------------------------------------
# 跨进程互斥锁：uvicorn（手动触发 /api/etl/run）与 etl-scheduler（定时触发）
# 是两个进程，模块级标志防不住对方。文件锁做在 run_once 入口，保证同一
# 时刻只有一个 ETL 在写 parquet 分区。fcntl 仅 POSIX；Windows 开发机退化为
# msvcrt。拿不到锁即视为「已有 ETL 在跑」。
# ---------------------------------------------------------------------------

class _EtlLock:
    """DATA_ROOT/.etl.lock 上的非阻塞排他文件锁。"""

    def __init__(self) -> None:
        self._fd = None

    def acquire(self) -> bool:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        fd = open(DATA_ROOT / ".etl.lock", "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            return False
        self._fd = fd
        return True

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


class EtlAlreadyRunningError(RuntimeError):
    """另一进程（或本进程）的 ETL 正在运行。"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException, ValueError)),
    reraise=True,
)
async def fetch_book_summary(client: httpx.AsyncClient, currency: str) -> List[Dict]:
    r = await client.get(
        f"{DERIBIT}/public/get_book_summary_by_currency",
        params={"currency": currency, "kind": "option"},
        timeout=30.0,
    )
    r.raise_for_status()
    d = r.json()
    return d.get("result", [])


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException, ValueError)),
    reraise=True,
)
async def fetch_instruments(client: httpx.AsyncClient, currency: str) -> Dict[str, Dict]:
    r = await client.get(
        f"{DERIBIT}/public/get_instruments",
        params={"currency": currency, "kind": "option", "expired": False},
        timeout=30.0,
    )
    r.raise_for_status()
    ins = r.json().get("result", [])
    out = {}
    for it in ins:
        out[it["instrument_name"]] = it
    return out


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException, ValueError)),
    reraise=True,
)
async def fetch_index_price(client: httpx.AsyncClient, currency: str) -> float:
    index_name = f"{currency.lower()}_usd"
    r = await client.get(
        f"{DERIBIT}/public/get_index_price",
        params={"index_name": index_name},
        timeout=30.0,
    )
    r.raise_for_status()
    result = r.json().get("result", {})
    return float(result.get("index_price", 0))


async def run_once(date_str: str, bases: List[str], notify: bool = False) -> None:
    lock = _EtlLock()
    if not lock.acquire():
        logger.warning("ETL skipped: another run is in progress (date=%s)", date_str)
        raise EtlAlreadyRunningError("another ETL run is in progress")
    try:
        await _run_once_locked(date_str, bases)
    finally:
        lock.release()

    # DVOL 日更：放在锁外执行，避免回填期间持续占用 ETL 互斥锁阻塞其他写入。
    # 顺带回填最近 7 天（按 (base, ts) 幂等去重），保持 IVP 序列新鲜。
    # 全量历史回填由 scripts/backfill_dvol.py 一次性执行。
    try:
        from scripts.backfill_dvol import backfill_base
        async with httpx.AsyncClient() as client:
            for base in bases:
                try:
                    await backfill_base(client, base, days=7)
                except Exception:
                    logger.error("DVOL daily update failed for %s", base, exc_info=True)
    except Exception:
        logger.error("DVOL daily update skipped", exc_info=True)

    # Telegram 推送（仅定时触发带 notify=True；手动刷新不打扰、避免同日重复推）。
    # 推送失败绝不反哺异常——通知是附属能力，不能影响 ETL 结果语义。
    if notify:
        try:
            from app.services import notify as notify_mod
            await notify_mod.push_daily_picks(date_str, bases)
            await notify_mod.check_dvol_jump(date_str, bases)
        except Exception:
            logger.error("notify step skipped", exc_info=True)


async def _run_once_locked(date_str: str, bases: List[str]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(tz=timezone.utc)
    asof_ts = int(now_utc.timestamp() * 1000)
    timestamp_str = now_utc.strftime("%Y-%m-%d-%H")
    dt_dir = DATA_ROOT / f"dt={timestamp_str}"
    dt_dir.mkdir(parents=True, exist_ok=True)

    logger.info("ETL start date=%s bases=%s", timestamp_str, bases)

    async with httpx.AsyncClient() as client:
        # 三组请求相互独立，单次 gather 全并发，缩短网络等待总时长
        n = len(bases)
        results = await asyncio.gather(
            *[fetch_book_summary(client, b) for b in bases],
            *[fetch_instruments(client, b) for b in bases],
            *[fetch_index_price(client, b) for b in bases],
            return_exceptions=True,
        )
        book_by_base = results[:n]
        ins_by_base = results[n:2 * n]
        index_prices = results[2 * n:]

    spot_prices = {}
    for b, result in zip(bases, index_prices):
        if isinstance(result, Exception):
            logger.error("Failed to fetch index price for %s: %s", b, result)
        elif not result or result <= 0:
            logger.error("Invalid index price for %s: %s", b, result)
        else:
            spot_prices[b] = result

    dvol_indices = {}
    for base, rows_raw, ins_raw, spot in zip(bases, book_by_base, ins_by_base, index_prices):
        if isinstance(rows_raw, Exception):
            logger.error("Failed to fetch book summary for %s: %s", base, rows_raw)
            continue
        if isinstance(ins_raw, Exception):
            logger.error("Failed to fetch instruments for %s: %s", base, ins_raw)
            continue
        if isinstance(spot, Exception) or not spot or spot <= 0:
            continue

        rows = rows_raw
        ins_map = ins_raw

        if not rows:
            continue

        atm_ivs = []
        for opt in rows:
            instrument_name = opt.get("instrument_name")
            meta = ins_map.get(instrument_name) if instrument_name else None
            if not meta:
                continue
            exp_ts = int(meta.get("expiration_timestamp", 0))
            strike = float(meta.get("strike", 0))
            mark_iv = opt.get("mark_iv")
            days_to_exp = (exp_ts - asof_ts) / (24 * 3600 * 1000)
            if 15 <= days_to_exp <= 60 and strike and abs(strike - spot) / spot < 0.15:
                if mark_iv and mark_iv > 0:
                    atm_ivs.append(mark_iv)
        dvol_indices[base] = round(sum(atm_ivs) / len(atm_ivs), 2) if atm_ivs else None

    manifest = {
        "date": date_str,
        "timestamp": timestamp_str,
        "asof_ts": asof_ts,
        # 仅记录实际成功写出 parquet 的 base，避免 manifest 误报未成功 base。
        "bases": [],
        "rows": 0,
        "expiries": {},
        "spot_prices": spot_prices,
        "dvol_indices": dvol_indices,
    }

    total_rows = 0
    for base, rows_raw, ins_raw in zip(bases, book_by_base, ins_by_base):
        if isinstance(rows_raw, Exception) or isinstance(ins_raw, Exception):
            continue

        rows = rows_raw
        ins_map = ins_raw

        if not rows:
            continue

        df = pd.DataFrame(rows)
        df = df.rename(
            columns={
                "instrument_name": "instrument",
                "bid_price": "bid",
                "ask_price": "ask",
                "open_interest": "oi",
                "underlying_price": "underlying",
            }
        )

        # 跳过未在 instruments 列表中的合约：ins_map.get(name) is None 时直接丢弃该行，
        # 避免向下游写出 strike=0 / expiry=0 的脏数据。
        df = df[df["instrument"].map(lambda name: ins_map.get(name) is not None)].reset_index(drop=True)
        if df.empty:
            continue

        strikes: List[float] = []
        types: List[str] = []
        expiries: List[int] = []
        bases_parsed: List[str] = []
        for name in df["instrument"].tolist():
            meta = ins_map.get(name)
            strikes.append(float(meta.get("strike")))
            types.append("C" if str(meta.get("option_type", "")).lower().startswith("c") else "P")
            expiries.append(int(meta.get("expiration_timestamp")))
            bases_parsed.append(str(meta.get("base_currency", base)))

        df["strike"] = strikes
        df["option_type"] = types
        df["expiry_ts"] = expiries
        df["base"] = bases_parsed
        df["date"] = date_str
        df["asof_ts"] = asof_ts

        # Deribit mark_iv 是百分数形式（42.5 表示 42.5%），统一归一为小数，
        # 供下游 BS delta / POP 计算直接使用
        df["mark_iv"] = pd.to_numeric(df["mark_iv"], errors="coerce") / 100.0

        exp_map: Dict[int, pd.DataFrame] = {}
        for exp_ts, grp in df.groupby("expiry_ts"):
            exp_map[int(exp_ts)] = grp

        for exp_ts, grp in exp_map.items():
            out_dir = dt_dir / f"base={base}" / f"expiry={int(exp_ts)}"
            out_dir.mkdir(parents=True, exist_ok=True)
            # 原子写入：先写临时文件再 rename，避免 API 读到半写文件
            tmp_parquet = out_dir / "chain.parquet.tmp"
            grp.to_parquet(tmp_parquet, index=False)
            os.replace(tmp_parquet, out_dir / "chain.parquet")

        manifest["expiries"][base] = sorted(list(exp_map.keys()))
        manifest["bases"].append(base)
        total_rows += int(df.shape[0])

        # SVI 拟合：逐到期切片（dte>=3 天），结果落 vol/history.parquet。
        # 该文件独立于 dt=* 分区，不受 backup_retention_days 清理影响；
        # 同日重复跑 ETL 按 (date, base, expiry_ts) 幂等覆盖。
        # 注：book_summary 的 volume / volume_usd 字段已随 df 全量落盘，无需另存。
        svi_rows = []
        for exp_ts, grp in exp_map.items():
            dte_days = (exp_ts - asof_ts) / (1000 * 60 * 60 * 24)
            if dte_days < 3:
                continue
            underlying_vals = pd.to_numeric(grp["underlying"], errors="coerce").dropna()
            if underlying_vals.empty:
                continue
            fit = fit_svi_slice(
                strikes=grp["strike"].to_numpy(dtype=float),
                ivs=pd.to_numeric(grp["mark_iv"], errors="coerce").to_numpy(dtype=float),
                ois=pd.to_numeric(grp["oi"], errors="coerce").to_numpy(dtype=float),
                forward=float(underlying_vals.median()),
                t_years=dte_days / 365.0,
            )
            svi_rows.append({
                "date": date_str,
                "asof_ts": asof_ts,
                "base": base,
                "expiry_ts": int(exp_ts),
                "dte": round(dte_days, 2),
                **fit,
            })
        if svi_rows:
            try:
                append_svi_rows(svi_rows)
                ok_n = sum(1 for r in svi_rows if r["quality"] == "ok")
                logger.info("SVI fit base=%s slices=%d ok=%d", base, len(svi_rows), ok_n)
            except Exception:
                logger.error("Failed to append SVI rows base=%s", base, exc_info=True)

    manifest["rows"] = total_rows
    tmp_manifest = dt_dir / "manifest.json.tmp"
    tmp_manifest.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp_manifest, dt_dir / "manifest.json")
    logger.info("ETL complete rows=%d bases=%s", total_rows, bases)

    cleanup_old_partitions(settings.backup_retention_days)


def cleanup_old_partitions(keep_days: int) -> None:
    """清理 DATA_ROOT 下的历史分区，防止磁盘无限增长。

    规则：
      * 同一天存在多个小时分区（手动多次触发 ETL）时只保留最新一个；
      * 分区时间早于 当前时间 - keep_days 的整目录删除。
    """
    if keep_days <= 0:
        return

    by_date: Dict[str, List[Path]] = {}
    for p in DATA_ROOT.glob("dt=*"):
        if p.is_dir():
            ts = p.name.split("=", 1)[1]
            by_date.setdefault(ts[:10], []).append(p)

    removed = 0
    # 同日去重：按目录名排序后仅保留最新
    for day, parts in by_date.items():
        parts.sort(key=lambda x: x.name)
        for old in parts[:-1]:
            shutil.rmtree(old, ignore_errors=True)
            removed += 1
            logger.info("Removed superseded partition %s", old.name)

    # 超期清理
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=keep_days)
    for parts in by_date.values():
        latest = parts[-1]
        ts = latest.name.split("=", 1)[1]
        try:
            part_dt = datetime.strptime(ts, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if part_dt < cutoff:
            shutil.rmtree(latest, ignore_errors=True)
            removed += 1
            logger.info("Removed expired partition %s", latest.name)

    if removed:
        logger.info("Partition cleanup done removed=%d keep_days=%d", removed, keep_days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default today UTC)")
    ap.add_argument("--bases", nargs="*", default=settings.etl_bases, help="Bases to fetch")
    args = ap.parse_args()

    date_str = args.date
    if not date_str:
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    asyncio.run(run_once(date_str, bases=args.bases))


if __name__ == "__main__":
    main()
