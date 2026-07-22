#!/bin/sh
set -e

# named volume 首次挂载时目录可能不存在，先创建并修正属主。
mkdir -p /app/data/parquet

# 首次启动数据为空时跑一次 ETL，避免冷启动 30 分钟内无数据可用。
# 之后的定时刷新由 supervisord 托管的 etl-scheduler 进程负责。
if [ -z "$(ls -A /app/data/parquet 2>/dev/null)" ]; then
    echo "[entrypoint] Data directory empty, running initial ETL..."
    cd /app
    PYTHONPATH=/app python /app/scripts/etl_daily.py
fi

exec "$@"
