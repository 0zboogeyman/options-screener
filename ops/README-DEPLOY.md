# 部署与运行指南

本项目按 `spread-finder-design.md` 设计，提供后端 FastAPI、前端 Next.js、每日 ETL 抓取脚本，以及基于 Docker Compose + PM2 的部署与调度。

建议遵循本环境规范：

- 端口范围：3115(后端) / 3116(前端)
- 绑定到本机回环：所有 `docker-compose` 端口映射均限制到 `127.0.0.1`，外部访问统一通过 Caddy 网关（由管理员配置）。
- 数据目录：`data/`（挂载到后端容器 `/app/data`）。

## 一键部署

```
bash ops/deploy.sh
```

部署脚本会执行：

- 构建并启动 `backend` 与 `frontend` 容器
- 进行一次“首份数据”抓取（UTC 当日）
- 预热 API（校验 `/api/meta/dates` 能返回）
- 通过 PM2 配置“每日北京时间 16:05”自动 ETL 调度

完成后，可在本机查看：

- 后端健康检查: `curl http://127.0.0.1:3115/api/health`
- 日期列表: `curl http://127.0.0.1:3115/api/meta/dates`
- 前端页面: `http://127.0.0.1:3116/spread-finder`

如需对外暴露，请联系管理员追加 Caddy 反向代理片段：

```
# 仅示例，需管理员应用到 /etc/caddy/sites
handle /spread-finder* {
    reverse_proxy 127.0.0.1:3116
}
handle /api* {
    reverse_proxy 127.0.0.1:3115
}
```

注意：请勿私自绑定 0.0.0.0 或自建反向代理，统一走现有网关。

## 常用操作

- 查看容器: `docker compose ps`
- 查看日志: `docker compose logs -f backend` / `frontend`
- 重启服务: `docker compose restart`
- 重新构建: `docker compose build --no-cache && docker compose up -d`

## ETL 调度

项目提供两种调度方式：

1) PM2（推荐）

```
# 设置 PM2 全局时区为上海（对 cron 生效）
pm2 set pm2:tz Asia/Shanghai

# 每天 16:05 运行 ETL（北京时间）。
pm2 start ops/etl_docker.sh \
  --name spread-etl \
  --cron "5 16 * * *"

# 持久化
pm2 save
```

2) Cron（如不使用 PM2）

```
CRON_TZ=Asia/Shanghai 5 16 * * * cd /home/kunkka/projects/spread-finder && /bin/bash -lc "ops/etl_docker.sh >> logs/etl.log 2>&1"
```

> 说明：`ops/etl_docker.sh` 会在已运行的 `backend` 容器内执行 `python /app/scripts/etl_daily.py`，将当日 UTC 数据写入 `data/parquet`。

## 安全基线

- 不修改系统配置、不开放系统特权端口
- 容器端口映射均限制在 `127.0.0.1`
- 后端/数据库/缓存仅监听本机或容器内网

## 验证步骤（完成验收）

1. 首次部署完成后：
   - `curl http://127.0.0.1:3101/api/meta/dates` 返回包含当日日期（UTC）的 JSON 列表
   - `curl -X POST http://127.0.0.1:3101/api/spread/scan -H 'Content-Type: application/json' -d '{"base":"BTC","date":"<返回的日期>","direction":"up","tenor":"near","return_per_bucket":3}'` 返回包含 `buckets` 的结果
   - 浏览器访问 `http://127.0.0.1:3102/spread-finder`，页面加载并展示结果卡片

2. 等待下一次每日调度（北京时间 16:05）后，`/api/meta/dates` 应新增日期。
