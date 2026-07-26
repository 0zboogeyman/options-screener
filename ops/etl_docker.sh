#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=7

usage() {
    echo "Usage: $0 {run|backup|restore <file>|list}"
    exit 1
}

do_etl() {
    echo "Running ETL inside option-scanner container..."
    if docker ps --format '{{.Names}}' | grep -q "^option-scanner$"; then
        docker exec option-scanner python /app/scripts/etl_daily.py
    else
        echo "ERROR: option-scanner container is not running"
        exit 1
    fi
}

do_backup() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    ARCHIVE="$BACKUP_DIR/data-$TIMESTAMP.tar.gz"
    echo "Creating backup of option-scanner-data volume: $ARCHIVE"
    docker run --rm -v option-scanner-data:/data -v "$PROJECT_DIR":/backup alpine \
        tar czf "/backup/backups/data-$TIMESTAMP.tar.gz" -C /data .
    echo "Backup complete: $(du -h "$ARCHIVE" | cut -f1)"

    echo "Cleaning backups older than ${RETENTION_DAYS} days..."
    find "$BACKUP_DIR" -name "data-*.tar.gz" -mtime +${RETENTION_DAYS} -delete
}

do_restore() {
    ARCHIVE="$1"
    if [ ! -f "$ARCHIVE" ]; then
        echo "ERROR: $ARCHIVE not found"
        exit 1
    fi
    echo "Restoring from: $ARCHIVE"
    docker compose down 2>/dev/null || true
    docker volume rm option-scanner-data 2>/dev/null || true
    REL="${ARCHIVE#$PROJECT_DIR/}"
    docker run --rm -v option-scanner-data:/data -v "$PROJECT_DIR":/backup alpine \
        tar xzf "/backup/$REL" -C /data
    docker compose up -d
    echo "Restore complete."
}

do_list() {
    mkdir -p "$BACKUP_DIR"
    echo "Available backups:"
    ls -lh "$BACKUP_DIR"/data-*.tar.gz 2>/dev/null || echo "  (none)"
}

[ $# -lt 1 ] && usage

case "$1" in
    run)    do_etl ;;
    backup) do_backup ;;
    restore) [ $# -lt 2 ] && usage; do_restore "$2" ;;
    list)   do_list ;;
    *)      usage ;;
esac
