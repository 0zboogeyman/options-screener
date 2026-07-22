#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Option Strategy Finder 单容器部署 ==="

echo "[1/4] 准备 .env 配置..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "    已从 .env.example 创建 .env，按需编辑后重新运行本脚本。"
else
    echo "    .env 已存在，沿用现有配置。"
fi

# 把 .env 变量导入当前 shell，供下方端口探测使用（docker compose 也会自动读 .env）
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

echo "[2/4] 停止旧容器..."
docker compose down 2>/dev/null || true

echo "[3/4] 构建并启动..."
docker compose up -d --build

echo "[4/4] 等待服务就绪..."
PORT="${PUBLIC_PORT:-3116}"
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
        echo "    服务就绪 (${i}s)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "    ⚠  启动超时，请查看日志: docker compose logs"
    fi
    sleep 2
done

echo ""
echo "=== 部署完成 ==="
echo "访问地址: http://YOUR_VPS_IP:${PORT}"
echo ""
echo "定时 ETL 由容器内调度器自动执行（默认每天台北 16:05），无需配置 crontab。"
echo "查看调度日志: docker compose logs app | grep etl"
