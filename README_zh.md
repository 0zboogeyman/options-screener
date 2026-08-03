[English](README.md) | **简体中文**

# Option Scanner

> 基于 Deribit 真实市场数据的多策略期权扫描器——垂直价差、担保卖 Put、备兑卖 Call、铁秃鹰、宽跨式、日历价差等策略，配合 raw SVI 拟合的波动率曲面与隐含风险中性密度（RND）推导的风险指标。

## 目录

- [项目概述](#项目概述)
- [核心功能](#核心功能)
- [算法亮点](#算法亮点)
- [目录结构](#目录结构)
- [安装步骤](#安装步骤)
- [使用指南](#使用指南)
- [配置说明](#配置说明)
- [API 参考](#api-参考)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

## 项目概述

Option Scanner 从 [Deribit](https://www.deribit.com) 公开 API 自动拉取每日 BTC/ETH 期权数据，落盘为本地 parquet 分区，用 raw SVI 模型按到期日拟合波动率微笑，并通过 Breeden-Litzenberger 隐含风险中性密度（RND）推导胜率与尾部风险。它扫描多种经典策略，用透明的 0–100 综合评分排序，最后通过单端口 Web 界面统一呈现。

### 架构

- **后端** — Python FastAPI（单容器，API 与前端静态导出同端口托管）。
- **前端** — Next.js 静态导出（`output: export`），三语言（英文 / 简体中文 / 繁体中文），由 FastAPI 直接托管，生产环境无需 Node.js 运行时。
- **数据管道** — 容器内 `etl-scheduler` 进程自动执行 ETL（默认 UTC 08:05 = 台北/北京时间 16:05），**无需配置 crontab**。
- **单容器** — Web、API、调度器全部由 supervisord 管理，运行在同一个 Docker 容器内。

## 核心功能

| 功能      | 端点                                       | 说明                                                                             |
| ------- | ---------------------------------------- | ------------------------------------------------------------------------------ |
| 到期日扫描  | `POST /api/spread/scan`                  | 按到期日扫描垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序；流动性惩罚排序、`mid`/`conservative` 双计价模式 |
| 观点策略   | `POST /api/spread/opinion`               | 基于目标价与方向观点（`up`/`down`/`not_up`/`not_down`）筛选最优价差                                  |
| 低吸收租   | `POST /api/strategy/csp`                 | 收权利金；若价格下跌，按折扣价买入标的。Delta、行权概率、APR、综合评分                                        |
| 高抛收租   | `POST /api/strategy/cc`                  | 收权利金；若价格上涨，按溢价卖出标的。上涨空间、APR、综合评分                                              |
| 铁秃鹰    | `POST /api/strategy/iron-condor`         | 卖 OTM Put 价差 + 卖 OTM Call 价差；SVI-delta 定位短腿，RND 计算胜率，保证金估算                            |
| 宽跨式    | `POST /api/strategy/strangle`            | OTM Put + OTM Call 组合，做多/做空波动率双侧返回；尾部风险为 RND 5% 期望亏损估计                             |
| 日历价差   | `POST /api/strategy/calendar`            | 卖近月 + 买远月同行权价；SVI 期限结构斜率 + theta 捕获差 + 利润区间数值求解                                    |
| 波动率面板  | `GET /api/meta/vol`                      | DVOL、IVP/IVR、SVI 期限结构（ATM IV / RR25 skew / BF25）、90 天 DVOL 趋势                        |
| 元数据    | `GET /api/meta/dates` `GET /api/meta/asof` | 可用日期、快照信息（现货价、DVOL 指数）                                                            |
| 手动 ETL | `POST /api/etl/run` `GET /api/etl/status`  | 一键刷新数据（需 `ADMIN_TOKEN` 口令）；前端「更新数据」按钮仅在口令有效时显示                                        |
| 健康检查   | `GET /api/health`                        | 服务状态、最新数据日期、数据过期告警                                                              |
| 地理位置   | `GET /api/geo`                           | 首次访问按 IP 自动识别语言（`zh-CN` / `zh-TW` / `en`）                                           |
| Telegram 推送 | （定时触发）                             | 每次定时 ETL 后推送：每日策略精选、DVOL 日环比跳变（>20%）告警、ETL 失败告警                                  |

## 算法亮点

### 1. SVI 波动率曲面

每个到期日独立拟合五参数 raw SVI 模型：

```
w(k) = a + b·(ρ·(k−m) + √((k−m)² + σ²))
```

使用 OI 开根号加权、3 组多初值优化、蝶式无套利校验；拟合失败时优雅回退到 `mark_iv`。结果每日落盘 `vol/history.parquet`。

### 2. RND — 隐含风险中性密度

由拟合曲面构建 Breeden-Litzenberger 密度：

```
pdf(k) = g(k)·n(d2(k)) / √w(k)
```

替代蒙特卡洛计算获胜概率（PoP）、VaR/CVaR 与尾部风险。它包含波动率微笑的肥尾特征，而纯对数正态（BS）模型会系统性低估尾部。

### 3. IVP / IVR

回填 DVOL 历史数据（`backfill_dvol.py`，日频 + continuation 翻页），在总方差空间插值 30 天固定期限 ATM IV，再计算 IV 百分位与 IV Rank。冷启动期（历史不足 30 天）IVR 返回 `null`，而非误导性的值。

### 4. 向量化 Black-Scholes 希腊字母

`delta_call_vec` / `vega_vec` / `theta_vec` / `gamma_vec`，以及 `prob_between` / `strike_from_delta_vec`——全部 numpy 向量化，单次扫描毫秒级完成。

### 5. Deribit 保证金估算

标准账户公式：裸卖 Call IM = `max(0.15 − OTM幅度, 0.10) + mark`；Put IM = `max(同上, MM_put)`；MM Call = `0.075 + mark`；Put MM = `max(0.075, 0.075·mark) + mark`（币种单位）。组合级函数同时输出币种与 USD 字段（标注 `estimate`）。

### 6. 双计价模式

- `mid` — 理论中间价。
- `conservative` — 可执行价（买腿付 ask、卖腿收 bid），更接近实际成交成本。

### 7. 工程优化

- `max_gap_steps` 将组合枚举复杂度从 `O(n²)` 降到 `O(n·g)`。
- `direction='both'` 将上下行扫描合并为一次请求。
- 进程内链缓存以 `(date, base)` 为键、`asof_ts` 为版本号；SVI 曲面 / DVOL 缓存以文件 mtime 为键。
- 综合评分过滤掉 45 分以下的候选（可配置常量），保证结果可执行。
- parquet 追加写入由跨进程文件锁保护；超过 30 天的分区自动清理。

## 目录结构

```
option-scanner/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 路由（扫描、策略、ETL、geo、meta）
│   │   ├── core/         # 配置、日志、限流
│   │   └── services/     # bs, svi, rnd, margin, scanner, single_leg, multi_leg,
│   │                     # loader, vol_history, notify, preprocessing
│   ├── scripts/          # etl_daily.py, etl_scheduler.py, backfill_dvol.py, cleanup_old_data.py
│   └── tests/            # pytest 测试套件（60 个用例）
├── frontend/             # Next.js 静态导出界面（三语言）
├── ops/                  # 部署脚本、Caddy 示例
├── Dockerfile.combined   # 单容器镜像（前端构建 + 后端 venv）
├── docker-compose.yml
├── supervisord.conf      # 托管 uvicorn + etl-scheduler
└── Makefile
```

## 安装步骤

### 前置要求

- Docker 20+ 与 Docker Compose v2（推荐路径）
- Node.js 20+ 与 Python 3.11+（本地开发路径）
- 服务器需能访问 Deribit API（`www.deribit.com`）

### 方式 A — Docker Compose（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/0zboogeyman/option-scanner.git
cd option-scanner

# 2. 首次部署：复制环境变量模板（所有变量都有内置默认值）
cp .env.example .env

# 3. 构建并启动
docker compose up -d --build
```

> 没有 `.env` 文件也能启动——`env_file` 设为 `required: false`，容器回退到源码内置默认值。

首次启动时若数据目录为空，容器会自动执行一次 ETL（约 1–3 分钟），完成后即可扫描。之后每日数据刷新由容器内调度器负责。

**访问**：`http://YOUR_SERVER_IP:3116`（根路径直接打开）。页面与 API 共用同一端口（容器端口 3000）。

### 方式 B — 本地开发

前端是静态导出、由 FastAPI 本身托管，因此最简本地方案是：先构建一次前端，再运行后端（后端会自动托管静态导出）。

```bash
# 1. 前端：安装依赖并构建静态导出（out/）
cd frontend
npm ci
npm run build

# 2. 后端：创建 venv 并安装依赖
cd ../backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 可选：预回填 DVOL 历史，让 IVP/IVR 立即可用
python scripts/backfill_dvol.py --days 365

# 4. 运行后端——页面与 API 同端口
python -m uvicorn app.main:app --reload --port 8000
# 访问 http://localhost:8000
```

> 开发环境手动跑一次 ETL：`python scripts/etl_daily.py`。
>
> 想在前端做 hot-reload 开发？在 `frontend/next.config.js` 中添加 `rewrites()` 将 `/api` 代理到后端（如 `http://localhost:8000`），再运行 `npm run dev`——详见常见问题 Q10。

## 使用指南

### 使用 Web 界面

1. 打开 `http://YOUR_SERVER_IP:3116`。
2. 选择 BTC 或 ETH，调整筛选条件，点击**扫描**。
3. 通过右上角语言选择器切换语言（English / 简体中文 / 繁體中文）。

### 手动更新数据

1. 在 `.env` 中设置 `ADMIN_TOKEN`（见[配置说明](#配置说明)）。
2. 访问一次 `https://your-domain/?admin=YOUR_TOKEN`——口令会自动存入 localStorage 并从 URL 中移除。
3. 页面顶部出现**更新数据**按钮。没有口令的访客看不到该按钮，直接调用 API 会返回 `401`。

### Telegram 推送

每次定时 ETL 完成后自动推送每日策略精选；DVOL 日环比跳变超过 20% 或 ETL 运行失败时也会发送告警。在 `.env` 中配置 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` 即可启用。手动触发的 ETL 不推送（避免同日重复）。

### Make 命令

| 命令             | 说明              |
| -------------- | --------------- |
| `make up`      | 构建并启动          |
| `make down`    | 停止容器           |
| `make restart` | 重启容器           |
| `make logs`    | 查看实时日志         |
| `make status`  | 容器状态 + 端口健康检查  |
| `make etl`     | 手动触发一次 ETL    |
| `make backup`  | 备份数据卷          |
| `make clean`   | 停止并删除容器与数据卷    |

### 备份与恢复

所有数据存放在 Docker 命名卷 `option-scanner-data`：

```bash
bash ops/etl_docker.sh backup                                # 备份
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz  # 恢复
```

## 配置说明

所有变量都有源码默认值，留空即用默认。编辑 `.env` 后重启：`docker compose up -d`。

| 变量                      | 说明                                                     | 默认值              |
| ----------------------- | ------------------------------------------------------ | ---------------- |
| `PUBLIC_PORT`           | 对外端口（反代场景改为 `127.0.0.1:3116`）                           | `3116`           |
| `CORS_ORIGINS`          | 跨域白名单 JSON 数组；禁止使用 `["*"]`                               | `[]`             |
| `LOG_LEVEL`             | `DEBUG` / `INFO` / `WARNING` / `ERROR`（生产环境禁止 `DEBUG`）      | `INFO`           |
| `ETL_SCHEDULE`          | ETL 调度（UTC）：`08:05`=台北 16:05、`@every 6h`、`@every 30m`、`off` | `08:05`          |
| `ETL_BASES`             | ETL 抓取币种                                               | `["BTC","ETH"]`  |
| `RATE_LIMIT_PER_MINUTE` | 扫描端点单 IP 限流（不建议低于 20）                                  | `30/minute`      |
| `API_DOCS_ENABLED`      | 开放 `/docs` `/redoc` `/openapi.json`（生产保持 `false`）          | `false`          |
| `DATA_STALE_HOURS`      | 数据过期告警阈值（小时）                                           | `25`             |
| `ADMIN_TOKEN`           | 手动 ETL 口令，经 `X-Admin-Token` 头校验（公网必填）                    | 空（放行）            |
| `TELEGRAM_BOT_TOKEN`    | Telegram Bot token（配合 `chat_id` 启用推送）                    | 空（禁用）            |
| `TELEGRAM_CHAT_ID`      | Telegram 接收人/群组 chat id                                 | 空（禁用）            |
| `TELEGRAM_LANG`         | Telegram 推送语言：`zh-CN` / `zh-TW` / `en`                  | `zh-CN`          |
| `GEO_ENABLED`           | IP 地理位置识别开关（`false` 则直接返回默认语言）                         | `true`           |
| `GEO_DEFAULT_LANG`      | 地理识别失败时的默认语言                                            | `zh-CN`          |

### 生产部署检查清单

1. **公网环境务必设置 `ADMIN_TOKEN`**——否则任何访客都能触发 ETL，消耗 Deribit API 配额。
2. **生产保持 `API_DOCS_ENABLED=false`** 且 `LOG_LEVEL=INFO`（或更高）。
3. **可选**：配置 Telegram 推送。
4. **可选**：通过反向代理绑定域名（见下），并将 `PUBLIC_PORT` 设为 `127.0.0.1:3116` 以屏蔽 IP:端口直连。

### 域名绑定与反向代理

`ops/Caddyfile.example` 提供了 Caddy 示例配置。Caddy 会自动签发并续期 Let's Encrypt 证书。

```bash
# 1. 容器仅绑定回环地址
#    .env
PUBLIC_PORT=127.0.0.1:3116

# 2. 配置 Caddy
cp ops/Caddyfile.example /etc/caddy/Caddyfile
vi /etc/caddy/Caddyfile          # 替换 yourdomain.com
systemctl reload caddy

# 3. 重启容器使新端口生效
docker compose up -d
```

## API 参考

| 方法   | 端点                          | 说明                    |
| ---- | --------------------------- | --------------------- |
| POST | `/api/spread/scan`          | 按到期日扫描垂直价差           |
| POST | `/api/spread/opinion`       | 目标价/方向观点价差           |
| POST | `/api/strategy/csp`         | 低吸收租（担保卖 Put）扫描      |
| POST | `/api/strategy/cc`          | 高抛收租（备兑卖 Call）扫描     |
| POST | `/api/strategy/iron-condor` | 铁秃鹰扫描                 |
| POST | `/api/strategy/strangle`    | 宽跨式扫描（做多/做空）          |
| POST | `/api/strategy/calendar`    | 日历价差扫描                |
| GET  | `/api/meta/vol`             | 波动率面板数据               |
| GET  | `/api/meta/dates`           | 可用日期                  |
| GET  | `/api/meta/asof`            | 某日期/币种的快照信息           |
| GET  | `/api/expiries`             | 某日期/币种的到期日            |
| POST | `/api/etl/run`              | 触发手动 ETL（需 `ADMIN_TOKEN`） |
| GET  | `/api/etl/status`           | ETL 运行状态               |
| GET  | `/api/geo`                  | IP 语言识别                |
| GET  | `/api/health`               | 健康检查                  |

设置 `API_DOCS_ENABLED=true` 可启用交互式文档（`/docs`）。

## 常见问题

### Q1：为什么数据是旧的 / 被标记为过期？
定时 ETL 每天执行一次，时间为 UTC 08:05（台北时间 16:05），紧接 Deribit 每日结算。若健康检查报数据过期，先查看调度器日志：
```bash
docker compose logs app | grep etl
```
也可以点击**更新数据**（需 `ADMIN_TOKEN`）立即触发一次。

### Q2：如何修改 ETL 时间或关闭调度？
编辑 `.env` 中的 `ETL_SCHEDULE` 并重启：
- `08:05` — 每天 UTC 08:05（默认）
- `@every 6h` — 每 6 小时
- `@every 30m` — 每 30 分钟
- `off` — 关闭（仅在首次启动时执行一次 ETL）

### Q3：为什么 IVR 显示 "—"？
IVR 至少需要 30 天的 DVOL 历史才具有统计意义。冷启动期内该值有意返回 `null`（界面显示 "—"），而非误导性的 0%。历史数据累积足够后 IVR 会自动出现。

### Q4：正常使用却遇到 HTTP 429（限流）？
默认限流为每 IP 每分钟 30 次请求，已覆盖前端正常交互。若仍触发，可在 `.env` 中调高 `RATE_LIMIT_PER_MINUTE`（不要低于 20，否则会破坏 UI 交互）。

### Q5：必须设置 ADMIN_TOKEN 吗？
任何公网部署都必须设置。否则 `POST /api/etl/run` 对所有人开放，任何访客都能触发 ETL 消耗 Deribit API 配额。请勿把口令提交到 git 历史。

### Q6：数据存放在哪里？如何备份？
数据存放在 Docker 命名卷 `option-scanner-data`（挂载于 `/app/data`），**位于项目目录之外**——重新克隆或重建镜像都不会丢失数据。用 `make backup` / `bash ops/etl_docker.sh backup` 备份。

### Q7：如何绑定域名并启用 HTTPS？
见[域名绑定与反向代理](#域名绑定与反向代理)。将 `PUBLIC_PORT` 设为 `127.0.0.1:3116`，让 Caddy 指向 `127.0.0.1:3116`，证书由 Caddy 自动处理。

### Q8：低内存 VPS 上 Docker 构建报 "cannot allocate memory"？
多阶段构建（npm ci + Next.js 构建 + pip install）非常吃内存。小内存 VPS 上请将构建与启动拆开，并在中间清理构建缓存：
```bash
docker compose build
docker compose down
docker builder prune -af
docker compose up -d
```

### Q9：`mid` 与 `conservative` 两种计价模式有何区别？
- `mid` — 理论中间价（买卖中间价，缺失时回退 mark price）。
- `conservative` — 可执行价：买腿付 ask、卖腿收 bid。结果更接近真实成交，但赔率/APR 会略低。

### Q10：开发时能对前端做 hot-reload 吗？
静态导出由 FastAPI 托管，仅运行 `npm run dev` 无法访问 API。在 `frontend/next.config.js` 中添加 rewrite：

```js
// frontend/next.config.js
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

然后后端跑在 8000 端口、前端运行 `npm run dev`。若长期保留该配置，提交前请移除。

## 免责声明

本项目**仅供教育与研究用途**，不构成任何投资建议。期权交易风险极高，一切盈亏由使用者自行承担。行情数据来自 Deribit 公开 API，可能存在延迟或错误。

## 致谢

本项目受到 [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder) 的启发，感谢原作者。
