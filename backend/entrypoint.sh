#!/bin/sh
set -e

if [ ! -d "/app/data/parquet" ] || [ -z "$(ls -A /app/data/parquet 2>/dev/null)" ]; then
    echo "[entrypoint] Data directory empty, running initial ETL..."
    python /app/scripts/etl_daily.py
fi

exec "$@"
