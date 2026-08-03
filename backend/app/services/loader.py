from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..core.config import settings

logger = logging.getLogger(__name__)

DATA_ROOT: Path = settings.data_root

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BASE_RE = re.compile(r"^(BTC|ETH)$")

# 进程内链数据缓存：(date, base) -> (asof_ts, df, meta)。
# 数据每天仅 ETL 变更一次；以 manifest.asof_ts 作版本号，ETL 写入新
# manifest 后旧缓存自动失效，无需显式清理。容量上限防止内存膨胀。
_CHAIN_CACHE: Dict[Tuple[str, str], Tuple[int, "pd.DataFrame", "ChainMeta"]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 4


def _date_dir(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise FileNotFoundError(f"Invalid date format: {date!r}")
    matching_dirs = sorted(DATA_ROOT.glob(f"dt={date}-*"), reverse=True)
    if matching_dirs:
        return matching_dirs[0]
    return DATA_ROOT / f"dt={date}"


def get_manifest(date: str) -> Dict:
    mpath = _date_dir(date) / "manifest.json"
    if not mpath.exists():
        raise FileNotFoundError(mpath)
    return json.loads(mpath.read_text())


def list_available_dates() -> List[str]:
    if not DATA_ROOT.exists():
        return []
    dates_set = set()
    for p in sorted(DATA_ROOT.glob("dt=*")):
        if p.is_dir():
            timestamp = p.name.split("=", 1)[1]
            date = timestamp[:10] if len(timestamp) >= 10 else timestamp
            if _DATE_RE.fullmatch(date):
                try:
                    datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    continue
                dates_set.add(date)
    return sorted(list(dates_set))


def get_latest_date() -> str:
    dates = list_available_dates()
    if not dates:
        raise FileNotFoundError("No data available")
    return dates[-1]


def list_expiries_for(date: str, base: str) -> List[int]:
    root = _date_dir(date)
    out: List[int] = []
    for p in sorted((root / f"base={base}").glob("expiry=*/chain.parquet")):
        exp = int(p.parent.name.split("=", 1)[1])
        out.append(exp)
    if not out:
        manifest = get_manifest(date)
        out = manifest.get("expiries", {}).get(base, [])
    return out


@dataclass
class ChainMeta:
    date: str
    asof_ts: int
    bases: List[str]
    spot_price: float | None = None
    dvol_index: float | None = None


def load_chain_for(date: str, base: str) -> Tuple[pd.DataFrame, ChainMeta]:
    """加载某日期/币种的期权链。

    缓存约定：调用方不得原地修改返回的 DataFrame（下游 prep_chain 会
    先 copy 再加工，已审查全部调用路径满足只读约束）。
    """
    if not _BASE_RE.fullmatch(base):
        raise ValueError(f"Invalid base: {base!r}")
    manifest_d = get_manifest(date)
    asof = int(manifest_d.get("asof_ts", 0))
    key = (date, base)

    with _CACHE_LOCK:
        hit = _CHAIN_CACHE.get(key)
        if hit is not None and hit[0] == asof:
            return hit[1], hit[2]

    root = _date_dir(date)
    parquet_paths = list((root / f"base={base}").glob("expiry=*/chain.parquet"))
    if not parquet_paths:
        parquet_paths = list(root.glob(f"**/base={base}/expiry=*/chain.parquet"))
    if not parquet_paths:
        raise FileNotFoundError(f"No parquet under {root} for base={base}")

    dfs = []
    for attempt in range(2):
        try:
            dfs = [pd.read_parquet(path) for path in parquet_paths]
            break
        except FileNotFoundError:
            if attempt == 1:
                logger.warning("Parquet disappeared during load: %s", root)
                raise FileNotFoundError(f"Parquet disappeared during load: {root}")
            logger.info("Parquet changed during load, refreshing paths: %s", root)
            parquet_paths = list((root / f"base={base}").glob("expiry=*/chain.parquet"))
            if not parquet_paths:
                parquet_paths = list(root.glob(f"**/base={base}/expiry=*/chain.parquet"))
    if not dfs:
        raise FileNotFoundError(f"No readable parquet under {root} for base={base}")
    df = pd.concat(dfs, ignore_index=True)
    logger.info("Loaded chain base=%s date=%s rows=%d", base, date, len(df))

    spot_prices = manifest_d.get("spot_prices", {})
    spot_price = spot_prices.get(base) if spot_prices else None

    dvol_indices = manifest_d.get("dvol_indices", {})
    dvol_index = dvol_indices.get(base) if dvol_indices else None

    meta = ChainMeta(
        date=date,
        asof_ts=asof,
        bases=manifest_d.get("bases", []),
        spot_price=spot_price,
        dvol_index=dvol_index,
    )

    with _CACHE_LOCK:
        if key not in _CHAIN_CACHE and len(_CHAIN_CACHE) >= _CACHE_MAX_ENTRIES:
            _CHAIN_CACHE.pop(next(iter(_CHAIN_CACHE)))  # 简单 FIFO 驱逐
        _CHAIN_CACHE[key] = (asof, df, meta)
    return df, meta


def get_data_status() -> Dict:
    try:
        dates = list_available_dates()
        latest = dates[-1] if dates else None
        return {
            "dates_available": len(dates),
            "latest_date": latest,
        }
    except Exception:
        return {"dates_available": 0, "latest_date": None}
