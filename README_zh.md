[English](README.md) | **简体中文**

# Options Screener

> 基于 Deribit 期权数据的多策略扫描工具——包括垂直价差、单腿收租、铁秃鹰、宽跨式、日历价差等策略。

## 功能

| 功能     | 端点                                         | 说明                                                                          |
| ------ | ------------------------------------------ | --------------------------------------------------------------------------- |
| 到期日扫描  | `POST /api/spread/scan`                    | 按到期日扫描垂直价差（CALL/PUT × DEBIT/CREDIT），赔率排序                                    |
| 观点策略   | `POST /api/spread/opinion`                 | 基于目标价和方向观点筛选最优价差                                                            |
| 低吸收租   | `POST /api/strategy/csp`                   | 担保卖 Put：跌至目标价按折扣价接币，否则收权利金；Delta、行权概率、APR、综合评分                              |
| 高抛收租   | `POST /api/strategy/cc`                    | 备兑卖 Call：涨至目标价按溢价出货，否则收权利金；上涨空间、APR、综合评分                                    |
| 铁秃鹰    | `POST /api/strategy/iron-condor`           | 四腿区间策略：卖 OTM Put 价差 + 卖 OTM Call 价差；SVI-delta 定位短腿，RND 计算胜率，保证金估算           |
| 宽跨式    | `POST /api/strategy/strangle`              | OTM Put + OTM Call 组合，做多/做空波动率双侧返回；尾部风险 RND 5% ES 估计                        |
| 日历价差   | `POST /api/strategy/calendar`              | 卖近月 + 买远月同行权价；SVI 期限结构斜率评分 + theta 捕获差 + 利润区间数值求解                           |
| 波动率面板  | `GET /api/meta/vol`                        | DVOL + IVP/IVR + SVI 期限结构（ATM IV / RR25 skew / BF25 kurtosis）+ 90 天 DVOL 趋势 |
| 元数据    | `GET /api/meta/dates` `GET /api/meta/asof` | 可用日期、快照信息（现货价、DVOL）                                                         |
| 手动 ETL | `POST /api/etl/run` `GET /api/etl/status`  | 一键刷新数据（需 `ADMIN_TOKEN` 口令）；前端「更新数据」按钮带口令才显示                                 |
| 健康检查   | `GET /api/health`                          | 服务状态、最新数据日期、数据陈旧告警                                                          |
| 地理位置   | `GET /api/geo`                             | 基于 IP 的语言自动识别（zh-CN/zh-TW/en）；前端首访调用                                        |

# 

## 快速部署

**前置要求**：Docker 20+ 与 Docker Compose v2，服务器能访问 Deribit API。

```bash
cp .env.example .env          # 首次部署；之后按需编辑 .env
docker compose up -d --build  # 构建并后台启动
```

> 没有 `.env` 也能启动：`env_file` 设为 `required: false`，容器回退到源码内置默认值。

首次启动若数据为空，容器自动跑一次 ETL（约 1–3 分钟），完成后即可扫描。

**访问**：`http://YOUR_VPS_IP:3116`（根路径直接打开），页面与 API 同源单端口（容器 8000）。

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
| `ADMIN_TOKEN`           | 手动 ETL 口令（`X-Admin-Token` 头校验；公网必填）               | 空（放行）           |
| `TELEGRAM_BOT_TOKEN`    | Telegram Bot token（配合 chat_id 启用推送）               | 空（禁用）           |
| `TELEGRAM_CHAT_ID`      | Telegram 接收人/群组 chat_id                           | 空（禁用）           |
| `GEO_ENABLED`           | IP 地理位置识别开关（`false` 则直接返回默认语言）                    | `true`          |
| `GEO_DEFAULT_LANG`      | 地理识别失败时的默认语言                                      | `zh-CN`         |

数据更新由容器内 `etl-scheduler` 进程自动执行，**无需配置 crontab**。
查看调度日志：`docker compose logs app | grep etl`。

## 生产部署要点

部署请逐项确认：

### 1. 必做：设置 ADMIN_TOKEN

`ADMIN_TOKEN` 是管理口令，保护 `POST /api/etl/run`（手动触发数据更新）。**不设置则任何访客都能触发 ETL**。

```bash
# .env —— 填一串足够长的随机字符串
ADMIN_TOKEN=你的随机口令
```

自用：浏览器访问 `https://你的域名/?admin=你的随机口令`，口令自动存入 localStorage，之后页面顶部常驻「更新数据」按钮（URL 中的口令参数会被自动清除）。访客没有口令——**看不到按钮，直接调 API 也会 401**。

### 2. 选配：Telegram 每日推送

定时 ETL 跑完后自动推送当日策略精选，DVOL 日环比跳变超 20% 或 ETL 失败时另有警报：

```bash
# .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...   # @BotFather /newbot 获取
TELEGRAM_CHAT_ID=123456789             # 先给 bot 发任意消息，再访问
                                       # https://api.telegram.org/bot<TOKEN>/getUpdates 查 chat.id
```

两项都填才启用，留空则静默跳过。手动触发的 ETL 不会推送（避免同日重复打扰）。

### 3. 选配：页面统计

示例配置 ops/site-config.example.js，通过**运行期配置文件**注入，修改后刷新页面即生效，**无需 rebuild 镜像**：

```bash
cp ops/site-config.example.js ops/site-override/site-config.js
vi ops/site-override/site-config.js
```

## 域名绑定与反向代理

已提供 Caddy 示例配置 [ops/Caddyfile.example](ops/Caddyfile.example)，使用步骤：

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

数据存储在 Docker named volume `option-scanner-data`：

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

## 算法与定价模型

本项目在算法层面的关键设计如下：

### 1. SVI 参数化波动率曲面

raw SVI 五参数模型拟合 `w(k) = a + b(ρ(k−m) + √((k−m)² + σ²))`，OI 开根号加权、3 组多初值优化器、butterfly 无套利校验。拟合失败时回退 mark_iv。每日 ETL 自动落盘至 `vol/history.parquet`。

### 2. RND 风险中性密度（Breeden-Litzenberger）

由 SVI 曲面构建隐含密度 `pdf(k)=g(k)·n(d2(k))/√w(k)`，替代蒙特卡洛计算 PoP / VaR / CVaR。含微笑肥尾，比 BS 对数正态更贴近真实风险。

### 3. IV 百分位 / IV Rank

DVOL 历史回填（`backfill_dvol.py`，resolution=1D，continuation 分页）→ 30d 固定期限总方差插值 → IVP/IVR 百分位。冷启动期由 DVOL 序列支撑。

### 4. Black-Scholes Greeks 向量化

`delta_call_vec` / `vega_vec` / `theta_vec` / `gamma_vec` + `prob_between` / `strike_from_delta_vec`，全 numpy 向量化，单次扫描 ~10ms。

### 5. Deribit 保证金估算

标准账户裸卖 Call IM=max(0.15−max((K−S)/S,0),0.10)+mark；Put IM=max(同结构, MM)；MM Call=0.075+mark、Put=max(0.075, 0.075·mark)+mark（币种单位）。组合级聚合，输出 `im_standard` 与 `max_loss` 双口径。

### 6. pricing_mode 双口径

`mid`=中间价（理论）；`conservative`=可执行价（买腿用 ask、卖腿用 bid），更贴近实际执行成本。

### 7. 其他工程优化

- `max_gap_steps` 限制组合枚举复杂度从 `O(n²)` 降为 `O(n·g)`
- numpy 向量化替代 `iterrows` 循环
- 进程内缓存 + `asof_ts` 版本号，消除冗余磁盘 I/O
- SVI surface mtime 缓存，扫描路径高频调用不重复读盘

## 致谢

本项目受 [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder)启发，感谢原作者的贡献。

## 免责声明

本项目仅供教育和研究用途，不构成任何投资建议。期权交易存在高风险，使用者需自行承担所有盈亏。数据来源于 Deribit 公开 API。
