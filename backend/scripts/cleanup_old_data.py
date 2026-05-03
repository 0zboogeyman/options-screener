#!/usr/bin/env python3
"""清理前一天的期权数据"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_ROOT = Path(__file__).parent.parent / "data" / "parquet"


def cleanup_old_data():
    """删除除了今天以外的所有旧数据目录"""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # 查找所有数据目录
    deleted_count = 0
    for target_dir in DATA_ROOT.glob("dt=*"):
        if not target_dir.is_dir():
            continue

        # 提取目录的日期部分（dt=YYYY-MM-DD 或 dt=YYYY-MM-DD-HH）
        dir_name = target_dir.name.split("=", 1)[1]
        dir_date = dir_name[:10] if len(dir_name) >= 10 else dir_name

        # 如果不是今天的数据，就删除
        if dir_date != today:
            shutil.rmtree(target_dir)
            print(f"[CLEANUP] Deleted: {target_dir}")
            deleted_count += 1

    if deleted_count == 0:
        print(f"[CLEANUP] No old data found (keeping today: {today})")
    else:
        print(f"[CLEANUP] Total deleted: {deleted_count} directories (kept today: {today})")


if __name__ == "__main__":
    cleanup_old_data()
