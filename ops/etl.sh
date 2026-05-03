#!/usr/bin/env bash
set -euo pipefail

# Run daily ETL snapshot for BTC and ETH into data/parquet
ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
cd "$ROOT_DIR"

PY="$ROOT_DIR/backend/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Python venv missing at backend/.venv. Please run: cd backend && uv venv && source .venv/bin/activate && uv pip install -r requirements.txt" >&2
  exit 1
fi

DATE_UTC=$(date -u +%F)
echo "[ETL] Starting snapshot for ${DATE_UTC} (UTC)"
"$PY" backend/scripts/etl_daily.py --date "$DATE_UTC"
echo "[ETL] Done."

