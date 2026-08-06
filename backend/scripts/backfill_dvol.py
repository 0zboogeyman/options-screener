#!/usr/bin/env python3
"""DVOL 历史回填：拉取 Deribit 波动率指数日频数据，落 vol/dvol_history.parquet。

用途：
  * 冷启动 IVP（IV 百分位）——自有 SVI ATM IV 序列需要从部署日起逐日累积，
    DVOL 是 30 天远期 IV 指数，可作 30d ATM IV 的代理，回填后 IVP 立即可用；
  * 之后 ETL 每天跑一次本脚本增量更新（或在 etl_scheduler 中调用）。

接口：GET /public/get_volatility_index_data
  参数：currency、start_timestamp/end_timestamp（毫秒）、resolution（"1D" 日频）
  返回：result.data = [[ts, open, high, low, close], ...]，超出单次上限时
        result.continuation 给出下一页起始 ts，循环翻页直至无 continuation。

用法：
  python scripts/backfill_dvol.py --days 365
  python scripts/backfill_dvol.py --days 365 --bases BTC ETH
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.vol_history import append_dvol_rows
from scripts.etl_daily import _retryable

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

DERIBIT: str = settings.deribit_api_url
PAGE_LIMIT_DAYS = 90  # 单页跨度保守取 90 天，配合 continuation 循环
MAX_PAGES = 1000      # 翻页上限，防 API 异常导致死循环（审计 D-5）


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception(_retryable),
    reraise=True,
)
async def fetch_dvol_page(
    client: httpx.AsyncClient, currency: str, start_ms: int, end_ms: int
) -> Dict:
    r = await client.get(
        f"{DERIBIT}/public/get_volatility_index_data",
        params={
            "currency": currency,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": "1D",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json().get("result", {})


async def backfill_base(client: httpx.AsyncClient, base: str, days: int) -> int:
    end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000

    rows: List[Dict] = []
    cursor = start_ms
    page_count = 0
    while cursor < end_ms and page_count < MAX_PAGES:
        page_count += 1
        page_end = min(cursor + PAGE_LIMIT_DAYS * 24 * 3600 * 1000, end_ms)
        result = await fetch_dvol_page(client, base, cursor, page_end)
        data = result.get("data", [])
        for ts, o, h, low, close in data:
            rows.append({
                "ts": int(ts),
                "date": datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "base": base,
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(close),
            })
        continuation = result.get("continuation")
        # 进度守卫：continuation 必须严格前进，否则回退到按页长推进，
        # 避免 API 异常导致死循环（审计 D-5）
        if continuation:
            try:
                next_cursor = int(continuation)
            except (TypeError, ValueError):
                next_cursor = -1
            cursor = next_cursor if next_cursor > cursor else page_end
        else:
            cursor = page_end

    if page_count >= MAX_PAGES:
        logger.error("DVOL backfill %s exceeded page limit %d, aborting", base, MAX_PAGES)
        return 0

    if not rows:
        logger.warning("No DVOL data for %s", base)
        return 0
    total = append_dvol_rows(rows)
    logger.info("DVOL backfill %s: +%d rows (total=%d)", base, len(rows), total)
    return len(rows)


async def run(days: int, bases: List[str]) -> None:
    async with httpx.AsyncClient() as client:
        for base in bases:
            try:
                await backfill_base(client, base, days)
            except Exception:
                logger.error("DVOL backfill failed for %s", base, exc_info=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365, help="回填天数（默认 365）")
    ap.add_argument("--bases", nargs="*", default=settings.etl_bases, help="币种")
    args = ap.parse_args()
    asyncio.run(run(args.days, args.bases))


if __name__ == "__main__":
    main()
