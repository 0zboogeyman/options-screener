# 期权策略推荐

> 基于 Deribit 期权数据的垂直价差与单腿策略扫描工具，**单容器一键部署**。
> FastAPI（后端）+ Next.js（前端）+ supervisord 进程托管，开箱即用。
> 仅作教育用途，不构成投资建议。

## 功能

| 功能     | 端点                                                             | 说明                                             |
| ------ | -------------------------------------------------------------- | ---------------------------------------------- |
| 到期日扫描  | `POST /api/spread/scan`                                        | 按到期日扫描所有行权价的垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序 |
| 观点策略   | `POST /api/spread/opinion`                                     | 基于目标价和方向观点筛选最优价差                               |
| CSP 买币 | `POST /api/strategy/csp`                                       | 卖出 Put 赚权利金，Delta、行权概率、APR、综合评分                |
| CC 卖币  | `POST /api/strategy/cc`                                        | 卖出 Call 赚权利金，上涨空间、APR、综合评分                     |
| 元数据    | `GET /api/meta/dates` `GET /api/expiries` `GET /api/meta/asof` | 可用日期、到期日、快照信息                                  |
| 健康检查   | `GET /api/health`                                              | 服务状态、最新数据日期、数据陈旧告警                             |

## 项目结构

```
option-strategy-single-container/
├── backend/                 后端源码（FastAPI + Pandas + SciPy）
│   ├── app/                 API 路由 / 配置 / 模型 / 服务
│   ├── scripts/             ETL 脚本（etl_daily.py + etl_scheduler.py）
│   ├── entrypoint.sh        容器入口（数据为空时自动 ETL）
│   └── requirements.txt
├── frontend/                前端源码（Next.js 14 + TypeScript）
├── ops/                     运维脚本（deploy.sh / etl_docker.sh / Caddyfile.example）
├── Dockerfile.combined      单容器镜像（三阶段构建）
├── supervisord.conf         容器内进程管理（backend + frontend + etl-scheduler）
├── docker-compose.yml       编排文件
├── .env.example             环境变量模板
├── .gitattributes           强制 LF 行尾
├── Makefile                 便捷命令
└── README.md
```

## 快速部署

### 前置要求

- Docker 20+ 与 Docker Compose v2
- 一台能访问 Deribit API（`https://www.deribit.com`）的服务器

### 方式一：一键脚本（推荐）

```bash
bash ops/deploy.sh
```

脚本会自动：从 `.env.example` 生成 `.env`（若不存在）→ 构建镜像 → 启动容器 → 探测服务就绪。

### 方式二：手动两条命令

```bash
cp .env.example .env          # 首次部署；之后按需编辑 .env
docker compose up -d --build  # 构建并后台启动
```

> 没有 `.env` 也能启动：`docker-compose.yml` 中 `env_file` 设为 `required: false`，
> 容器会回退到源码内置默认值。生成 `.env` 只是为了自定义端口、CORS、调度等。

### 访问

- **页面**：`http://YOUR_VPS_IP:3116`（根路径直接打开，无需输入子路径）
- **API**：`http://YOUR_VPS_IP:3116/api/health`（前端同源代理，无需单独端口）

首次启动若数据为空，容器会自动跑一次 ETL（约 1–3 分钟），完成后即可扫描。

## 配置（.env）

复制 `.env.example` 为 `.env` 后按需修改。所有变量都有源码默认值，留空即用默认。

| 变量                      | 说明                                                            | 默认值                              |
| ----------------------- | ------------------------------------------------------------- | -------------------------------- |
| `PUBLIC_PORT`           | 对外暴露端口（IP+端口直连）                                               | `3116`                           |
| `CORS_ORIGINS`          | 跨域白名单 JSON 数组；IP+端口直连留 `[]`，绑域名填 `["https://yourdomain.com"]` | `[]`                             |
| `ETL_SCHEDULE`          | ETL 调度（UTC）：`08:05`=每天台北16:05 / `@every 6h` / `off`           | `08:05`                          |
| `ETL_BASES`             | ETL 抓取币种                                                      | `["BTC","ETH"]`                  |
| `LOG_LEVEL`             | 日志级别 DEBUG/INFO/WARNING/ERROR                                 | `INFO`                           |
| `DATA_STALE_HOURS`      | 数据过期告警阈值（小时）                                                  | `25`                             |
| `RATE_LIMIT_PER_MINUTE` | 扫描端点单 IP 限流                                                   | `30/minute`                      |
| `API_DOCS_ENABLED`      | 是否开放 `/docs` `/redoc`                                         | `false`                          |
| `DERIBIT_API_URL`       | Deribit API 地址                                                | `https://www.deribit.com/api/v2` |
| `DATA_ROOT`             | 容器内数据路径                                                       | `/app/data/parquet`              |

## ETL 定时调度

数据更新由容器内 `etl-scheduler` 进程（supervisord 托管）自动执行，**无需配置 crontab**。

- 默认 `08:05 UTC` = **台北/北京时间 16:05**（Deribit 每日 16:00 结算后 5 分钟抓数）
- 想改时间：编辑 `.env` 的 `ETL_SCHEDULE` 后 `docker compose up -d` 重启即可
- 关闭调度：`ETL_SCHEDULE=off`（仅首次启动跑一次）
- 查看调度日志：`docker compose logs app | grep etl`

> 时区换算：台北/北京 = UTC + 8。想要台北 XX:YY → 填 UTC `(XX-8):YY`。

## 绑定域名（可选）

IP+端口直连已能满足使用。若要绑定域名 + HTTPS，用 Caddy 反代：

1. 安装 Caddy（`apt install caddy`）
2. 把 `ops/Caddyfile.example` 复制到 `/etc/caddy/Caddyfile`，将 `yourdomain.com` 改为你的真实域名
3. `systemctl restart caddy`（Caddy 自动申请 Let's Encrypt 证书）
4. 在 `.env` 中把 `PUBLIC_PORT` 改为 `127.0.0.1:3116:3000`（仅本机可见，由 Caddy 对外）

Caddy 规则：`/api/*` → 容器后端 `127.0.0.1:3115`，其余 → 前端 `127.0.0.1:3116`。

## 备份与恢复

数据存储在 Docker named volume `spread-data`，用临时容器导出，不依赖宿主目录权限：

```bash
bash ops/etl_docker.sh backup                                    # 备份
bash ops/etl_docker.sh list                                      # 查看备份
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz      # 恢复
```

## Make 命令

| 命令             | 说明                                |
| -------------- | --------------------------------- |
| `make up`      | 构建并启动                             |
| `make down`    | 停止                                |
| `make restart` | 重启                                |
| `make logs`    | 实时日志（backend + frontend + etl 交错） |
| `make status`  | 容器状态 + 端口健康                       |
| `make etl`     | 手动触发一次 ETL                        |
| `make backup`  | 备份 spread-data 卷                  |
| `make clean`   | 停止并删除容器与卷                         |

## 架构

```
宿主机 :3116 ──┐
               │   ┌─► uvicorn  :8000   FastAPI   /api/*
宿主机 :3115 ──┼──►容器(supervisord)──┼─► node     :3000   Next.js   /
(仅本机)        │   └─► etl_scheduler   定时 ETL
               │      volume: spread-data → /app/data/parquet
```

- `:3116` 对外暴露 → Next.js，`/api/*` 经 rewrite 同源代理到后端
- `:3115` 仅本机 → 后端直连，供反向代理使用

## 常见问题

**Q：页面打不开 / 一直加载？**
首启动正在跑 ETL，约 1–3 分钟。`docker compose logs -f app` 看到 `etl_daily` 完成即可。

**Q：扫描返回 404？**
确认前端构建时 `NEXT_PUBLIC_BASE_PATH` 为空（默认即是）。`docker compose logs app` 检查 Next.js 与后端是否都 RUNNING。

**Q：ETL 没按时执行？**
`docker compose logs app | grep etl.scheduler` 查看调度器日志，确认 `ETL_SCHEDULE` 值与时区换算。

**Q：改了 .env 不生效？**
`docker compose up -d` 重启容器（环境变量在容器启动时注入）。

**Q：端口被占用？**
改 `.env` 的 `PUBLIC_PORT` 为其他端口后重启。

## 免责声明

本项目仅供教育和研究用途，不构成任何投资建议。期权交易存在高风险，
使用者需自行承担所有盈亏。数据来源于 Deribit 公开 API。
项目地址：https://github.com/0zBoogeyman/option-strategy-finder
