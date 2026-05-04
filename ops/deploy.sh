#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Option Strategy Finder 部署 ==="

echo "[1/5] 停止旧容器..."
docker compose down 2>/dev/null || true

echo "[2/5] 确保数据目录存在..."
mkdir -p ./data/parquet
chmod 755 ./data ./data/parquet 2>/dev/null || true

echo "[3/5] 构建镜像..."
docker compose build

echo "[4/5] 启动服务..."
docker compose up -d

echo "[5/5] 等待后端健康检查..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3115/api/health > /dev/null 2>&1; then
        echo "后端健康检查通过 (${i}s)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "⚠  后端启动超时，请检查日志: docker compose logs backend"
    fi
    sleep 2
done

echo ""
echo "=== 部署完成 ==="
echo "后端: http://localhost:3115/api/health"
echo "前端: http://localhost:3116/spread-finder"
echo ""
echo "数据尚未初始化? 运行: docker exec spread-backend python /app/scripts/etl_daily.py"
echo "配置定时ETL:  crontab -e  添加  5 16 * * * docker exec spread-backend python /app/scripts/etl_daily.py"
