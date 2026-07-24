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

生产环境**强烈建议**通过反向代理（Nginx / Caddy）+ 域名访问，并禁用直接公网 IP:port 访问，原因：
1. 启用 HTTPS（Deribit API 与前端均要求安全上下文）
2. 隐藏真实 VPS IP，降低被扫描攻击面
3. 便于后续接入 WAF、限流、CDN

### 配置步骤

**1. 修改 `.env`，让容器仅监听本地回环**

```bash
PUBLIC_PORT=127.0.0.1:3116
```

> 此后 `http://VPS_IP:3116` 将拒绝连接，仅 `127.0.0.1:3116` 可访问，反向代理转发至此。

**2. 配置反向代理**

Nginx 示例（HTTP→HTTPS 自动跳转，反代到本地 3116）：

```nginx
server {
    listen 80;
    server_name qiquan.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name qiquan.example.com;

    ssl_certificate     /etc/letsencrypt/live/qiquan.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/qiquan.example.com/privkey.pem;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:3116;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

Caddy 示例（自动申请并续期证书，配置更简洁）：

```caddy
qiquan.example.com {
    reverse_proxy 127.0.0.1:3116
}
```

**3. 申请 SSL 证书**

```bash
# Nginx + certbot
certbot --nginx -d qiquan.example.com

# Caddy 自动处理，无需手动申请
```

**4. 重启服务并验证**

```bash
docker compose up -d            # 应用新的 PUBLIC_PORT
nginx -t && systemctl reload nginx   # 或 systemctl restart caddy

curl -I https://qiquan.example.com        # 应返回 200
curl -I http://VPS_IP:3116                # 应拒绝连接（证实直连已禁用）
```

### 常见问题

| 现象 | 排查方向 |
|------|---------|
| 反代 502 Bad Gateway | 容器未监听 127.0.0.1:3116，检查 `docker compose ps` 与 `.env` |
| 反代 200 但前端白屏 | `basePath` 配置错误，本项目要求 `basePath=""`（空） |
| WebSocket / SSE 失败 | Nginx 缺少 `proxy_http_version 1.1` 与 Upgrade 头 |
| 限流误触发 | 反代未透传 `X-Forwarded-For`，后端把所有请求当作单 IP |

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

本项目相对原始仓库在算法层面做了以下关键改进，提升推荐准确性与候选质量：

### 1. Black-Scholes 严格解替代启发式 Delta

- **原版**：基于 `moneyness = K/S` 的 4 段折线近似估算 delta，未考虑隐含波动率与剩余期限，在 moneyness=0.9 断点处误差可达 57%
- **本项目**：采用 BS 模型解析解 `delta = N(d1)`，完整考虑 S、K、σ、T、r 五变量，并提供 numpy 向量化版本 `delta_call_vec` / `delta_put_vec`

### 2. mark_iv 单位归一化

- **原版**：Deribit API 返回的 `mark_iv` 为百分数形式（42.5 表示 42.5%），未做转换直接代入 BS 公式，导致 `d2 → 0`、POP 全部聚集在 0.5 附近，丧失区分能力
- **本项目**：ETL 阶段 `/100.0` 归一为小数，`prep_chain` 阶段增加 `>5.0` 启发式兜底，保证历史数据兼容性

### 3. spread_ratio 流动性阈值优化

价差策略扫描器 `scanner.py` 中 `SPREAD_RATIO_MAX` 控制单腿买卖价差过滤上限。本项目基于 Deribit 真实市场数据（BTC+ETH 1412 样本）系统性评估后，将阈值从原版 `0.5` 收紧至 `0.35`：

| 指标 | 原版 0.5 | 本项目 0.35 | 改善 |
|------|---------|------------|------|
| F1（分类性能） | 0.768 | 0.775 | +0.007 |
| Recall（召回率） | 0.995 | 0.987 | -0.8% |
| 平均赔率 avg_odds | 34.27 | 23.89 | **-30%** |

阈值收紧后候选池平均赔率下降 30%，剔除了大量"高赔率但不可执行"的灰尘期权噪声，候选质量显著提升，同时核心 Top 候选重叠率 > 90%。

### 4. 其他工程优化

- `max_gap_steps=10` 将组合枚举复杂度从 `O(n²)` 降为 `O(n·g)`
- numpy 向量化替代 `iterrows` 循环，单次扫描延迟从 ~260ms 降至 ~10ms
- 进程内 `(date, base)` 缓存 + `asof_ts` 版本号，消除冗余磁盘 I/O

## 致谢

本项目来源于 [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder)，感谢原作者的开源贡献。本项目对原项目进行了向量化计算、数据缓存等方面的性能优化，并进行了单容器部署重构与前端改进。

## 免责声明

本项目仅供教育和研究用途，不构成任何投资建议。

期权交易存在高风险，使用者需自行承担所有盈亏。

数据来源于 Deribit 公开 API。
