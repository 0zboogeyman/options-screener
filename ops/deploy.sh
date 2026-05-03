#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
cd "$ROOT_DIR"

mkdir -p logs data

echo "[Deploy] Building images..."
docker compose build

echo "[Deploy] Starting services..."
docker compose up -d

echo "[Deploy] Running initial ETL (today UTC)..."
DATE_UTC=$(date -u +%F)
docker compose exec -T backend python /app/scripts/etl_daily.py --date "$DATE_UTC"

echo "[Deploy] Warm up API..."
sleep 2
curl -fsS http://127.0.0.1:3115/api/health || true
curl -fsS http://127.0.0.1:3115/api/meta/dates || true

echo "[Deploy] Configure PM2 schedule (Asia/Shanghai 16:05 daily)"
if command -v pm2 >/dev/null 2>&1; then
  pm2 set pm2:tz Asia/Shanghai || true
  pm2 delete spread-etl >/dev/null 2>&1 || true
  pm2 start ops/etl_docker.sh --name spread-etl --cron "5 16 * * *"
  pm2 save || true
  echo "[Deploy] PM2 job 'spread-etl' installed."
else
  echo "[Deploy] pm2 not found; skip schedule. You can add cron or install pm2. See ops/README-DEPLOY.md"
fi

echo "[Deploy] Done. Frontend: http://127.0.0.1:3116/spread-finder  Backend: http://127.0.0.1:3115/api/health"
