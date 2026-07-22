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

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

DATA_ROOT: Path = settings.data_root
DERIBIT: str = settings.deribit_api_url


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
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
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
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
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
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


async def run_once(date_str: str, bases: List[str]) -> None:
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
        "bases": bases,
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

        strikes: List[float] = []
        types: List[str] = []
        expiries: List[int] = []
        bases_parsed: List[str] = []
        for name in df["instrument"].tolist():
            meta = ins_map.get(name)
            if meta:
                strikes.append(float(meta.get("strike")))
                types.append("C" if str(meta.get("option_type", "")).lower().startswith("c") else "P")
                expiries.append(int(meta.get("expiration_timestamp")))
                bases_parsed.append(str(meta.get("base_currency", base)))
            else:
                strikes.append(0.0)
                types.append("P")
                expiries.append(0)
                bases_parsed.append(base)

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
        total_rows += int(df.shape[0])

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
