# PM2 生态系统配置说明

## 当前 PM2 进程

项目使用 PM2 管理三个进程：

### 1. spread-finder-api
**后端 FastAPI 服务**
```bash
TS_IP=$(tailscale ip -4 | head -n1)
pm2 start /bin/bash \
  --name spread-finder-api \
  --cwd /home/kunkka/projects/spread-finder \
  -- -lc "backend/.venv/bin/uvicorn backend.app.main:app --host ${TS_IP} --port 3115 --workers 2 --root-path /spread-finder"
```

### 2. spread-finder-web
**前端 Next.js 服务**
```bash
TS_IP=${TS_IP:-$(tailscale ip -4 | head -n1)}
pm2 start /bin/bash \
  --name spread-finder-web \
  --cwd /home/kunkka/projects/spread-finder/frontend \
  -- -lc "HOST=${TS_IP} HOSTNAME=${TS_IP} PORT=3117 NEXT_PUBLIC_BASE_PATH=/spread-finder \
    NEXT_PUBLIC_API_PROXY_DEST=http://${TS_IP}:3115 node .next/standalone/server.js"
```

### 3. spread-finder-etl
**ETL 定时任务 (每小时整点执行)**
```bash
cd /home/kunkka/projects/spread-finder/backend
pm2 start "uv run python scripts/etl_daily.py --bases BTC ETH --date \$(date -u +%Y-%m-%d)" \
  --name spread-finder-etl \
  --cron "0 * * * *" \
  --no-autorestart
```
⚠️ **重要**: 必须添加 `--no-autorestart` 参数，否则任务会持续重启导致 asof_ts 不断更新

## 快速操作命令

### 查看状态
```bash
pm2 list | grep spread-finder
```

### 查看日志
```bash
# 实时查看所有日志
pm2 logs spread-finder

# 查看特定服务
pm2 logs spread-finder-api
pm2 logs spread-finder-web
pm2 logs spread-finder-etl
```

### 重启服务
```bash
# 重启后端（代码更新后）
pm2 restart spread-finder-api

# 重启前端（代码或构建更新后）
pm2 restart spread-finder-web

# ETL 任务会按 cron 自动执行，无需手动重启
# 如需立即执行一次：
cd /home/kunkka/projects/spread-finder/backend
uv run python scripts/etl_daily.py --bases BTC ETH
```

### 停止服务
```bash
pm2 stop spread-finder-api
pm2 stop spread-finder-web
pm2 stop spread-finder-etl
```

### 保存配置
```bash
pm2 save
```

## 开机自启动

如需配置开机自启动：
```bash
pm2 startup
# 按照输出的命令执行（需要 sudo）
pm2 save
```

## 环境变量

### 后端环境变量
- `PYTHONUNBUFFERED=1` - 禁用 Python 输出缓冲

### 前端环境变量
- `NEXT_PUBLIC_BASE_PATH=/spread-finder` - Next.js 基础路径
- `NEXT_PUBLIC_API_PROXY_DEST` - API 代理目标（生产环境使用 `http://<tailscale-ip>:3115`）

## 更新部署流程

### 后端代码更新
```bash
cd /home/kunkka/projects/spread-finder/backend
# 拉取最新代码
git pull

# 更新依赖（如有变化）
uv pip install -r requirements.txt

# 重启服务
pm2 restart spread-finder-api
```

### 前端代码更新
```bash
cd /home/kunkka/projects/spread-finder/frontend
# 拉取最新代码
git pull

# 安装依赖（如有变化）
npm install

# 重新构建
TS_IP=$(tailscale ip -4 | head -n1) \
NEXT_PUBLIC_BASE_PATH=/spread-finder \
NEXT_PUBLIC_API_PROXY_DEST=http://${TS_IP}:3115 \
npm run build

# 重启服务
pm2 restart spread-finder-web
```

### ETL 脚本更新
```bash
cd /home/kunkka/projects/spread-finder/backend
# 拉取最新代码
git pull

# 测试运行
uv run python scripts/etl_daily.py --bases BTC ETH

# 无需重启，下次 cron 触发时自动使用新代码
```

## 监控与告警

### 健康检查
```bash
# 后端健康检查
TS_IP=${TS_IP:-$(tailscale ip -4 | head -n1)}
curl http://${TS_IP}:3115/spread-finder/api/health
# 预期输出: {"status":"ok"}

# 前端健康检查
curl -I http://${TS_IP}:3117/spread-finder
# 预期: HTTP 200

# 检查数据是否最新
curl http://${TS_IP}:3115/spread-finder/api/meta/dates | jq
```

### 使用 Apprise 发送通知
项目可以集成 Apprise 进行告警通知（参考 `~/APPRISE_GUIDE.md`）

示例 - ETL 失败告警：
```bash
# 在 etl_daily.py 中添加异常处理
apprise -b "ETL failed for $(date)" "<your-apprise-url>"
```

## 资源限制

根据用户配置：
- **端口范围**: 3101-3200
- **当前使用**: 3115 (API), 3000 (Web, 内部)
- **内存**: 8GB
- **CPU**: 200%

## 故障排查

### 服务启动失败
```bash
# 查看详细错误
pm2 logs spread-finder-api --err --lines 50

# 检查端口占用
netstat -tuln | grep -E '3115|3000'

# 手动运行测试
cd /home/kunkka/projects/spread-finder/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 3115
```

### ETL 任务未执行
```bash
# 检查 cron 配置
pm2 info spread-finder-etl | grep cron

# 查看最后一次执行日志
pm2 logs spread-finder-etl --lines 100

# 手动触发测试
cd /home/kunkka/projects/spread-finder/backend
uv run python scripts/etl_daily.py --bases BTC ETH
```

---

**最后更新**: 2025-10-03
**维护人员**: kunkka
