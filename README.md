# Option Strategy Finder

基于 Deribit 期权数据的垂直价差与单腿策略扫描工具。

- 后端：Python FastAPI + Pandas + NumPy + SciPy（Black-Scholes 模型）
- 前端：Next.js (Pages Router) + TypeScript
- 部署：Docker Compose + Caddy 反向代理

## 项目结构

```
option-strategy-finder/
├── backend/
│   ├── app/
│   │   ├── api/                # FastAPI 路由
│   │   │   ├── routes_meta.py          # 元数据：数据日期、到期日列表
│   │   │   ├── routes_spread.py        # 垂直价差 + 观点策略扫描
│   │   │   └── routes_single_leg.py    # CSP / CC 单腿策略扫描
│   │   ├── core/               # 配置与日志
│   │   │   ├── config.py               # Pydantic Settings（.env 支持）
│   │   │   └── logging.py             # 结构化 JSON 日志
│   │   ├── models/             # Pydantic 数据模型
│   │   │   └── dto.py
│   │   ├── services/           # 核心业务层
│   │   │   ├── bs.py                   # Black-Scholes 模型 & Delta
│   │   │   ├── loader.py              # Parquet 数据加载
│   │   │   ├── preprocessing.py       # 数据预处理（中间价、质量标记）
│   │   │   ├── quality.py             # 买卖价差质量评估
│   │   │   ├── scanner.py             # 垂直价差 & 观点策略扫描器
│   │   │   └── single_leg.py          # CSP / CC 单腿策略扫描器
│   │   └── main.py            # FastAPI 入口（CORS、限流、异常处理）
│   ├── scripts/
│   │   ├── etl_daily.py       # 每日 ETL：从 Deribit 拉取数据写入 Parquet
│   │   └── cleanup_old_data.py # 清理历史数据
│   ├── .dockerignore
│   ├── Dockerfile
│   ├── entrypoint.sh          # 容器入口（自动初始化数据）
│   └── requirements.txt
├── frontend/
│   ├── pages/                 # Next.js 页面
│   ├── components/            # React 组件
│   ├── types/                 # TypeScript 类型集中定义
│   ├── styles/                # 全局 CSS
│   ├── public/                # 静态资源
│   ├── .dockerignore
│   ├── Dockerfile
│   ├── next.config.js
│   ├── package.json
│   └── tsconfig.json
├── ops/
│   ├── deploy.sh              # 一键部署脚本
│   ├── etl_docker.sh          # ETL / 备份 / 恢复工具
│   └── Caddyfile.example      # 反向代理参考配置
├── docker-compose.yml
├── Makefile                   # 快捷命令集
├── .env.example               # 环境变量参考
├── .gitignore
└── README.md
```

## 功能

| 功能 | 说明 |
|------|------|
| 到期日扫描 | 按指定到期日扫描所有行权价的垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序 |
| 观点策略 | 基于目标价和方向观点（涨/跌/不涨/不跌），筛选最优价差策略 |
| CSP 买币 | 卖出 Put 赚权利金，BS Delta、行权概率、APR、综合评分 |
| CC 卖币 | 卖出 Call 赚权利金，上涨空间、APR、综合评分 |

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/0zBoogeyman/option-strategy-finder.git
cd option-strategy-finder

# 构建并启动（自动初始化空数据目录）
make deploy

# 首次数据采集
make etl

# 设置定时采集（每天北京时间 16:05）
# crontab -e  添加：
# 5 16 * * * cd /path/to/option-strategy-finder && make etl
```

## Make 命令

| 命令 | 说明 |
|------|------|
| `make build` | 仅构建 Docker 镜像 |
| `make up` | 启动所有服务 |
| `make down` | 停止所有服务 |
| `make restart` | 重启服务 |
| `make logs` | 查看实时日志（tail -f） |
| `make status` | 容器状态 + 后端健康检查 |
| `make etl` | 执行每日数据采集 |
| `make backup` | 备份 data 目录（自动保留 7 天） |
| `make deploy` | 一键部署（构建 → 启动 → 健康检查） |
| `make clean` | 清理容器和数据卷 |

## ETL 运维工具

```bash
bash ops/etl_docker.sh run              # 手动执行 ETL
bash ops/etl_docker.sh backup           # 备份数据到 backups/
bash ops/etl_docker.sh list             # 列出已有备份
bash ops/etl_docker.sh restore <file>   # 从备份恢复
```

## VPS 部署

1. 克隆项目到 VPS
2. 复制 `ops/Caddyfile.example` 到 `/etc/caddy/Caddyfile`，根据域名调整
3. 执行 `bash ops/deploy.sh`
4. 配置定时 ETL（见上方 crontab 示例）

## 环境变量

复制 `.env.example` 为 `.env` 并修改。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CORS_ORIGINS` | 跨域白名单（生产必改为具体域名） | `["*"]` |
| `DATA_ROOT` | 数据存储路径 | `./data/parquet` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `DATA_STALE_HOURS` | 数据过期告警阈值 | `25` |
| `DERIBIT_API_URL` | Deribit API 地址 | `https://www.deribit.com/api/v2` |

## 技术栈

- **期权定价**：Black-Scholes 模型（`scipy.stats.norm.cdf`），POP 概率计算
- **Delta 计算**：`delta_call` / `delta_put` 基于 BS 模型标准公式
- **数据质量**：bid/ask 中间价、质量标记（ok / missing / wide_spread / invalid）
- **限流保护**：`slowapi` 基于 IP，扫描端点 10次/分钟，策略端点 20次/分钟
- **重试机制**：`tenacity` 指数退避，Deribit API 调用自动重试 3 次
- **结构化日志**：JSON 格式 `{"ts":"...","level":"INFO","message":"..."}`

## 免责声明

本项目**仅供教育和研究用途**，不构成任何投资建议。期权交易存在高风险，使用者需自行承担所有盈亏。数据来源于 Deribit 公开 API。

## 致谢

原作者 [Kunkka](https://github.com/xiaochongkun/option-strategy-finder) from SignalPlus。  
二次开发 [0zBoogeyman](https://github.com/0zBoogeyman/option-strategy-finder)。
