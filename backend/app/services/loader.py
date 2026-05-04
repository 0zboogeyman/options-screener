from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from ..core.config import settings

logger = logging.getLogger(__name__)

DATA_ROOT: Path = settings.data_root


def _date_dir(date: str) -> Path:
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
    root = _date_dir(date)
    parquet_paths = list((root / f"base={base}").glob("expiry=*/chain.parquet"))
    if not parquet_paths:
        parquet_paths = list(root.glob(f"**/base={base}/expiry=*/chain.parquet"))
    if not parquet_paths:
        raise FileNotFoundError(f"No parquet under {root} for base={base}")

    dfs = [pd.read_parquet(p) for p in parquet_paths]
    df = pd.concat(dfs, ignore_index=True)
    logger.info("Loaded chain base=%s date=%s rows=%d", base, date, len(df))

    manifest_d = get_manifest(date)
    spot_prices = manifest_d.get("spot_prices", {})
    spot_price = spot_prices.get(base) if spot_prices else None

    dvol_indices = manifest_d.get("dvol_indices", {})
    dvol_index = dvol_indices.get(base) if dvol_indices else None

    meta = ChainMeta(
        date=date,
        asof_ts=int(manifest_d.get("asof_ts", 0)),
        bases=manifest_d.get("bases", []),
        spot_price=spot_price,
        dvol_index=dvol_index,
    )
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
