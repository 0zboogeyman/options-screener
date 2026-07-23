# Options Screener

> 基于 Deribit 期权数据的垂直价差与单腿策略扫描工具，**单容器一键部署**。
> FastAPI（后端）+ Next.js（前端）+ supervisord 进程托管，开箱即用。
> 仅作教育用途，不构成投资建议。

## 功能

| 功能 | 端点 | 说明 |
| --- | --- | --- |
| 到期日扫描 | `POST /api/spread/scan` | 按到期日扫描垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序 |
| 观点策略 | `POST /api/spread/opinion` | 基于目标价和方向观点筛选最优价差 |
| CSP 买币 | `POST /api/strategy/csp` | 卖出 Put 赚权利金，Delta、行权概率、APR、综合评分 |
| CC 卖币 | `POST /api/strategy/cc` | 卖出 Call 赚权利金，上涨空间、APR、综合评分 |
| 元数据 | `GET /api/meta/dates` `GET /api/meta/asof` | 可用日期、快照信息（现货价、DVOL） |
| 健康检查 | `GET /api/health` | 服务状态、最新数据日期、数据陈旧告警 |

## 快速部署

**前置要求**：Docker 20+ 与 Docker Compose v2，服务器能访问 Deribit API。

```bash
cp .env.example .env          # 首次部署；之后按需编辑 .env
docker compose up -d --build  # 构建并后台启动
```

> 没有 `.env` 也能启动：`env_file` 设为 `required: false`，容器回退到源码内置默认值。

首次启动若数据为空，容器自动跑一次 ETL（约 1–3 分钟），完成后即可扫描。

**访问**：`http://YOUR_VPS_IP:3116`（根路径直接打开），API 同源代理 `/api/*`。

## 配置（.env）

所有变量都有源码默认值，留空即用默认。

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `PUBLIC_PORT` | 对外端口（绑域名时改为 `127.0.0.1:3116:3000`） | `3116` |
| `CORS_ORIGINS` | 跨域白名单 JSON 数组 | `[]` |
| `ETL_SCHEDULE` | ETL 调度（UTC）：`08:05`=台北16:05 / `@every 6h` / `off` | `08:05` |
| `ETL_BASES` | ETL 抓取币种 | `["BTC","ETH"]` |
| `RATE_LIMIT_PER_MINUTE` | 扫描端点单 IP 限流 | `30/minute` |
| `DATA_STALE_HOURS` | 数据过期告警阈值（小时） | `25` |

数据更新由容器内 `etl-scheduler` 进程自动执行，**无需配置 crontab**。
查看调度日志：`docker compose logs app | grep etl`。

## 备份与恢复

数据存储在 Docker named volume `options-screener-data`：

```bash
bash ops/etl_docker.sh backup                                # 备份
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz  # 恢复
```

## Make 命令

| 命令 | 说明 |
| --- | --- |
| `make up` | 构建并启动 |
| `make down` / `restart` / `logs` | 停止 / 重启 / 实时日志 |
| `make status` | 容器状态 + 端口健康 |
| `make etl` | 手动触发一次 ETL |
| `make backup` | 备份数据卷 |
| `make clean` | 停止并删除容器与卷 |

## 致谢

本项目 Fork 自 [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder)，
感谢原作者的开源贡献。在本 Fork 中进行了算法修正（Black-Scholes delta、mark_iv 单位归一）、
性能优化（向量化计算、数据缓存）、单容器部署重构与前端改进。

## 免责声明

本项目仅供教育和研究用途，不构成任何投资建议。期权交易存在高风险，
使用者需自行承担所有盈亏。数据来源于 Deribit 公开 API。
