from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


DATA_ROOT = Path(__file__).parent.parent.parent / "data" / "parquet"


def _date_dir(date: str) -> Path:
    """获取指定日期的最新时间戳目录"""
    # 查找该日期的所有时间戳目录（dt=YYYY-MM-DD-HH 格式）
    matching_dirs = sorted(DATA_ROOT.glob(f"dt={date}-*"), reverse=True)
    if matching_dirs:
        return matching_dirs[0]  # 返回最新的（小时最大的）
    # 向后兼容：如果没有找到带时间戳的，尝试旧格式
    return DATA_ROOT / f"dt={date}"


def get_manifest(date: str) -> Dict:
    mpath = _date_dir(date) / "manifest.json"
    if not mpath.exists():
        raise FileNotFoundError(mpath)
    return json.loads(mpath.read_text())


def list_available_dates() -> List[str]:
    """列出所有可用的日期（YYYY-MM-DD格式）"""
    if not DATA_ROOT.exists():
        return []
    dates_set = set()
    for p in sorted(DATA_ROOT.glob("dt=*")):
        if p.is_dir():
            timestamp = p.name.split("=", 1)[1]
            # 提取日期部分（YYYY-MM-DD），去掉小时部分（-HH）
            date = timestamp[:10] if len(timestamp) >= 10 else timestamp
            dates_set.add(date)
    return sorted(list(dates_set))


def get_latest_date() -> str:
    """获取最新的数据日期"""
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
        # fall back to manifest if written differently
        manifest = get_manifest(date)
        out = manifest.get("expiries", {}).get(base, [])
    return out


@dataclass
class ChainMeta:
    date: str
    asof_ts: int
    bases: List[str]
    spot_price: float | None = None  # 新增：标准现货指数价格
    dvol_index: float | None = None  # 新增：DVOL波动率指数


def load_chain_for(date: str, base: str) -> Tuple[pd.DataFrame, ChainMeta]:
    root = _date_dir(date)
    # support both layout styles: base/expiry and flat expiry folders
    parquet_paths = list((root / f"base={base}").glob("expiry=*/chain.parquet"))
    if not parquet_paths:
        # try layout: dt=/base=BTC/expiry=... else dt=/expiry=.../base=BTC
        parquet_paths = list(root.glob(f"**/base={base}/expiry=*/chain.parquet"))
    if not parquet_paths:
        raise FileNotFoundError(f"No parquet under {root} for base={base}")

    dfs = [pd.read_parquet(p) for p in parquet_paths]
    df = pd.concat(dfs, ignore_index=True)

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

