#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
cd "$ROOT_DIR"

DATE_UTC=$(date -u +%F)
echo "[ETL] docker-compose exec backend for ${DATE_UTC} (UTC)"
docker compose exec -T backend python /app/scripts/etl_daily.py --date "$DATE_UTC"
echo "[ETL] done."

