# Options Screener

> 基于 Deribit 期权数据的垂直价差与单腿策略扫描工具，FastAPI（后端）+ Next.js（前端）+ supervisord 进程托管，开箱即用。
> 仅作教育用途，不构成投资建议。

## 功能

| 功能     | 端点                                         | 说明                                       |
| ------ | ------------------------------------------ | ---------------------------------------- |
| 到期日扫描  | `POST /api/spread/scan`                    | 按到期日扫描垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序 |
| 观点策略   | `POST /api/spread/opinion`                 | 基于目标价和方向观点筛选最优价差                         |
| CSP 买币 | `POST /api/strategy/csp`                   | 卖出 Put 赚权利金，Delta、行权概率、APR、综合评分          |
| CC 卖币  | `POST /api/strategy/cc`                    | 卖出 Call 赚权利金，上涨空间、APR、综合评分               |
| 元数据    | `GET /api/meta/dates` `GET /api/meta/asof` | 可用日期、快照信息（现货价、DVOL）                      |
| 健康检查   | `GET /api/health`                          | 服务状态、最新数据日期、数据陈旧告警                       |

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

| 变量                      | 说明                                                | 默认值             |
| ----------------------- | ------------------------------------------------- | --------------- |
| `PUBLIC_PORT`           | 对外端口（绑域名时改为 `127.0.0.1:3116`）                     | `3116`          |
| `CORS_ORIGINS`          | 跨域白名单 JSON 数组                                     | `[]`            |
| `ETL_SCHEDULE`          | ETL 调度（UTC）：`08:05`=台北16:05 / `@every 6h` / `off` | `08:05`         |
| `ETL_BASES`             | ETL 抓取币种                                          | `["BTC","ETH"]` |
| `RATE_LIMIT_PER_MINUTE` | 扫描端点单 IP 限流                                       | `30/minute`     |
| `DATA_STALE_HOURS`      | 数据过期告警阈值（小时）                                      | `25`            |

数据更新由容器内 `etl-scheduler` 进程自动执行，**无需配置 crontab**。
查看调度日志：`docker compose logs app | grep etl`。

## 域名绑定与反向代理

生产环境建议通过 Caddy 反向代理 + 域名访问，并禁用直接公网 IP:port 访问，以启用 HTTPS、隐藏 VPS IP。

仓库已提供 Caddy 示例配置 [ops/Caddyfile.example](ops/Caddyfile.example)，使用步骤：

1. 修改 `.env`，让容器仅监听本地回环：
   
   ```bash
   PUBLIC_PORT=127.0.0.1:3116
   ```

2. 复制并编辑 Caddyfile，将 `yourdomain.com` 替换为你的真实域名：
   
   ```bash
   cp ops/Caddyfile.example /etc/caddy/Caddyfile
   vi /etc/caddy/Caddyfile
   systemctl reload caddy
   ```

3. 重启容器应用新的 `PUBLIC_PORT`：
   
   ```bash
   docker compose up -d
   ```

Caddy 会自动申请并续期 Let's Encrypt 证书，无需额外操作。配置完成后 `https://yourdomain.com` 可访问，`http://VPS_IP:3116` 拒绝连接。

## 备份与恢复

数据存储在 Docker named volume `options-screener-data`：

```bash
bash ops/etl_docker.sh backup                                # 备份
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz  # 恢复
```

## Make 命令

| 命令                               | 说明             |
| -------------------------------- | -------------- |
| `make up`                        | 构建并启动          |
| `make down` / `restart` / `logs` | 停止 / 重启 / 实时日志 |
| `make status`                    | 容器状态 + 端口健康    |
| `make etl`                       | 手动触发一次 ETL     |
| `make backup`                    | 备份数据卷          |
| `make clean`                     | 停止并删除容器与卷      |

## 算法优化

本项目在算法层面的关键设计与优化如下：

### 1. Black-Scholes 严格 Delta 计算

本项目采用 Black-Scholes 模型解析解 `delta = N(d1)` 计算期权 delta，完整考虑标的价 S、行权价 K、隐含波动率 σ、剩余期限 T、无风险利率 r 五个变量，并提供 numpy 向量化版本 `delta_call_vec` / `delta_put_vec`。

### 2. mark_iv 单位归一化

Deribit API 返回的 `mark_iv` 为百分数形式（42.5 表示 42.5%），本项目在 ETL 阶段 `/100.0` 归一为小数后存储，`prep_chain` 阶段增加 `>5.0` 启发式兜底（兼容历史数据），保证 BS 公式计算的准确性。

### 3. spread_ratio 流动性阈值

价差策略扫描器 `scanner.py` 中 `SPREAD_RATIO_MAX = 0.35` 控制单腿买卖价差过滤上限：单腿 `(ask - bid) / mid > 0.35` 视为流动性不足，扫描时剔除。该阈值基于 Deribit 真实市场数据系统性评估确定，在分类性能（F1=0.775）、召回率（0.987）与候选质量（avg_odds=23.89）之间取得最佳平衡，剔除"高赔率但不可执行"的灰尘期权噪声。

### 4. 其他工程优化

- `max_gap_steps=10` 将组合枚举复杂度从 `O(n²)` 降为 `O(n·g)`
- numpy 向量化替代 `iterrows` 循环，单次扫描延迟从 ~260ms 降至 ~10ms
- 进程内 `(date, base)` 缓存 + `asof_ts` 版本号，消除冗余磁盘 I/O

## 致谢

本项目来源于 [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder)，感谢原作者的开源贡献。

## 免责声明

本项目仅供教育和研究用途，不构成任何投资建议。

期权交易存在高风险，使用者需自行承担所有盈亏。

数据来源于 Deribit 公开 API。
