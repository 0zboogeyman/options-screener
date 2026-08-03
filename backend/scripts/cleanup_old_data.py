#!/usr/bin/env python3
"""历史分区清理脚本（可手动执行）。

复用 etl_daily.cleanup_old_partitions 的清理规则：
  * 同一天存在多个小时分区（手动多次触发 ETL）时只保留最新一个；
  * 分区时间早于 当前时间 - backup_retention_days 的整目录删除。

注意：早期版本曾错误地删除所有非当天分区（保留 1 天），导致历史数据
（SVI 期限结构 / IVP / IVR 计算依赖的历史窗口）全部丢失。此版本按
backup_retention_days（默认 30 天）保留足够历史，供 IVR 等指标冷启动。
"""
from __future__ import annotations

from app.core.config import settings
from scripts import etl_daily


def main() -> None:
    keep_days = settings.backup_retention_days
    etl_daily.cleanup_old_partitions(keep_days)


if __name__ == "__main__":
    main()
