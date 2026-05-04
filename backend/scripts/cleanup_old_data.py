#!/usr/bin/env python3
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

DATA_ROOT = settings.data_root


def cleanup_old_data():
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    deleted_count = 0
    for target_dir in DATA_ROOT.glob("dt=*"):
        if not target_dir.is_dir():
            continue

        dir_name = target_dir.name.split("=", 1)[1]
        dir_date = dir_name[:10] if len(dir_name) >= 10 else dir_name

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
