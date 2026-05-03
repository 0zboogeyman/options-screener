# 期权价差筛选器 - 项目需求设计文档

## 背景
目标是实现一个「**期权价差筛选器**」的在线项目。  
数据来源：Deribit 公共 API。  
运行模式：每日抓取一次或两次期权链快照（EOD），存档后用户在前端选择方向与到期档位，系统筛选并返回赔率最佳与最差的期权价差策略（借方/贷方）。  
支持历史数据浏览与简单的 POP（Probability of Profit）估算。

---

## 一、项目目标

1. 用户输入：
   - 标的（BTC/ETH）
   - 日期（默认最新存档，可选历史）
   - 方向（上涨/下跌）
   - 到期档位（近月/中期/远期）
2. 系统返回：
   - Call 与 Put 的 **借方/贷方价差策略**
   - 各类策略的 **赔率 Top3 和 Bottom3**
   - 结果字段：权利金、最大盈亏、盈亏平衡点、赔率、POP
   - 质量标记（点差过宽/仅单边报价）

---

## 二、技术选型

- **后端**：Python 3.11 + FastAPI
- **ETL**：独立脚本 `scripts/etl_daily.py`
- **存储**：Parquet(ZSTD/Snappy) 分区存档，结构 `dt=YYYY-MM-DD/base=BTC/expiry=...`
- **计算**：Numpy/Scipy（Black-Scholes 定价与 POP）
- **前端**：Next.js + Tailwind
- **容器化**：Docker + docker-compose
- **质量**：pydantic 模型、pytest 单测

---

## 三、数据来源 (Deribit API)

主要接口：
- `/public/get_book_summary_by_currency` (kind=option)  
  返回所有期权的摘要：`bid, ask, mark_price, mark_iv, oi, underlying_price, expiry, strike`
- `/public/get_instruments` (kind=option, expired=false)  
  用于校验合约清单

清洗规则：
- 缺失 bid/ask → 用 mid 或 theo 替补
- 点差阈值 `(ask - bid)/mid > 0.15` → 标记 wide_spread
- 添加字段：`quality_flag`

---

## 四、ETL 脚本设计

### 功能
- 每日或每日两次抓取 BTC/ETH 全链快照（“T 型报价簿”= 以到期 × 行权价栅格形成的整链摘要）
- 清洗并写入 Parquet 分区
- 写出 `manifest.json`（包含 date, bases, expiries, rows, asof_ts）

### 存储结构
```
data/parquet/
  dt=2025-09-30/
    base=BTC/expiry=1735603200000/chain.parquet
    base=ETH/expiry=1735603200000/chain.parquet
    manifest.json
```

### 字段最小集
- `date, base, instrument, expiry_ts, strike, option_type`
- `bid, ask, mid, mark_price, mark_iv, underlying, oi`
- `asof_ts, quality_flag`

---

## 五、策略与计算逻辑

### 组合定义（Vertical Spreads）
- Call Debit：Buy Call(K1), Sell Call(K2)
- Call Credit：Sell Call(K1), Buy Call(K2)
- Put Debit：Buy Put(K2), Sell Put(K1)
- Put Credit：Sell Put(K2), Buy Put(K1)

### 计算指标
- **净权利金**：
  - Debit: long - short
  - Credit: short - long
- **最大盈亏**：
  - Debit: max_profit = (K2 - K1) - premium, max_loss = premium
  - Credit: max_profit = premium, max_loss = (K2 - K1) - premium
- **盈亏平衡点**：
  - Call Debit: K1 + premium
  - Call Credit: K2 - premium
  - Put 对称
- **赔率**：max_profit / max_loss
- **POP**：
  - 使用 Black-Scholes 对数正态模型
  - 输入：S, σ=mark_iv, T, r≈0
  - 求净收益≥0 的价格区间概率

---

## 六、筛选逻辑

用户选择：
- `direction`：up / down
- `tenor`：near (7–21d) / mid (22–60d) / far (61–180d)
- `base`：BTC / ETH
- 可选：点差阈值、最小 OI、最大档距

后端：
- 按日期加载对应快照
- 枚举同到期 K1<K2 的价差组合
- 按 `odds` 排序，取 Top3 和 Bottom3
- 返回四类（Call/Put × Debit/Credit）结果

---

## 七、API 设计

### 1) 列出历史日期
`GET /api/meta/dates`  
响应：
```json
{ "dates": ["2025-09-28","2025-09-29","2025-09-30"] }
```

### 2) 查询到期列表
`GET /api/expiries?base=BTC&date=2025-09-30`  
返回该日期的到期时间列表

### 3) 筛选接口
`POST /api/spread/scan`  
请求：
```json
{
  "base": "BTC",
  "date": "2025-09-30",
  "direction": "up",
  "tenor": "near",
  "return_per_bucket": 3
}
```
响应：
```json
{
  "asof_date": "2025-09-30",
  "base": "BTC",
  "tenor": "near",
  "buckets": [
    {
      "leg_type": "CALL",
      "side": "DEBIT",
      "top": [
        { "K1": 50000, "K2": 52000, "premium": 450,
          "max_profit": 1550, "max_loss": 450,
          "odds": 3.44, "pop": 0.41 }
      ],
      "bottom": [ ... ]
    }
  ]
}
```

### 4) 数据元信息
`GET /api/meta/asof?base=BTC&date=2025-09-30`  
返回该日期快照的 `asof_ts`、来源（EOD/收盘）

---

## 八、前端交互

### 控件
- Base 下拉：BTC / ETH
- 日期选择器：默认最新，可选历史
- 方向选择：上涨 / 下跌
- 到期档位选择：近月 / 中期 / 远期
- 高级选项：点差阈值、最小 OI

### 展示
- 顶部显示 “数据更新于 2025-09-30 23:59 UTC (本地时区 …)”
- 筛选结果分为 4 个卡片：
  - Call Debit
  - Call Credit
  - Put Debit
  - Put Credit
- 每个卡片有 Top3 和 Bottom3 的表格
- 鼠标悬停 → 弹出盈亏曲线/腿明细

---

## 九、历史数据支持

- 每个日期有单独分区
- `/api/meta/dates` 返回所有存档日期
- 用户可自由选择历史日查询
- 延迟低（单日数据几千行，本地计算 <1s）
- 存储压力小（全年 <1GB）

---

## 十、扩展功能 (TODO)

- 开盘/收盘双存档
- 支持导出历史数据：`/api/export?date=...`
- 增加点差模型回归，用于估计 bid/ask
- 增加 CSV/Excel 下载
- 扩展到更多标的

---

## 十一、上线与调度（初始缓存 + 北京时间 16:05 EOD 抓取）

本项目采用“**上线首日即刻缓存** + **次日起每日定时抓取**”的模式：

### A. 上线初始（首启）
- **目的**：在没有历史的情况下，使用“当前时刻”的 Deribit 链摘要生成**首份快照与缓存**，保证页面立即可用。
- **操作**：
  ```bash
  # 进入 backend 环境或容器
  python scripts/etl_daily.py \
    --base BTC --base ETH \
    --date $(date -u +%F) \
    --out ./data/parquet
  ```
- **效果**：产出 `data/parquet/dt=YYYY-MM-DD/...` 与对应的 `manifest.json`；后端启动后默认读取该分区并在内存中**预热缓存**（可选：将最近一次快照加载为只读切片，减少首次查询 IO）。

### B. 次日起每日定时（北京时间 16:05）
- **机制**：北京时间（CST, UTC+8）**16:05** 运行 ETL，抓取“最新 T 型报价簿”（即整链摘要）生成当日快照，用于后续 24 小时的计算展示。中国大陆无夏令时，时间固定。
- **Cron（主机时区为 UTC）**：
  ```cron
  # 08:05 UTC == 16:05 北京时间（UTC+8）
  5 8 * * *  /usr/bin/python /app/scripts/etl_daily.py --base BTC --base ETH --date $(date -u +\%F) --out /app/data/parquet >> /var/log/etl.log 2>&1
  ```
- **Cron（若容器/主机时区已设为 Asia/Shanghai）**：
  ```cron
  5 16 * * * /usr/bin/python /app/scripts/etl_daily.py --base BTC --base ETH --date $(date +\%F) --out /app/data/parquet >> /var/log/etl.log 2>&1
  ```
- **PM2 计划任务（可选）**：
  在 `ops/ecosystem.config.cjs` 中添加一个 `cron_restart` 样例或使用 `pm2 start etl.js --cron "5 16 * * *"`（容器时区为 Asia/Shanghai 时）。

### C. ETag/缓存与一致性
- ETL 完成后写入 `manifest.json`：`{date,bases,expiries,rows,asof_ts,source:"EOD"}`；写入采用**临时文件 → 原子替换**。
- 后端在收到新分区后：
  - **自动选用最新 `dt=`** 作为“默认日期”；
  - 将 `asof_ts` 暴露在 `/api/meta/asof`，前端角标显示“数据更新于 …”。
- 前端可在“今日”视图中每 **5–15 分钟**轮询 `/api/meta/asof`，若变化则提示“数据更新，可刷新页面”。（不需要 WS 即可完成体验）

### D. 失败与回退
- ETL 失败则**保留上一日分区**继续对外服务；日志报警并重试（指数退避 3 次）。
- 若当天 16:05 之后补抓成功，将覆盖或追加 `dt=YYYY-MM-DD` 分区，后端自动切换。

---

## 十二、文件结构

```
spread-finder/
  backend/
    app/
      main.py
      api/
        routes_spread.py
        routes_meta.py
      services/
        loader.py
        scanner.py
        bs.py
        quality.py
      models/dto.py
    scripts/etl_daily.py
    tests/
    requirements.txt
    Dockerfile
  frontend/
    pages/index.tsx
    components/
      Controls.tsx
      ResultBucket.tsx
      AsOfBadge.tsx
    package.json
    Dockerfile
  docker-compose.yml
  data/sample/ (示例存档)
  ops/ (可选：部署脚本、PM2 配置、反代样例)
```

---

## 十三、默认参数

- TENOR_NEAR_DTE = [7, 21]
- TENOR_MID_DTE = [22, 60]
- TENOR_FAR_DTE = [61, 180]
- MAX_WIDE_SPREAD_RATIO = 0.15
- MIN_OPEN_INTEREST = 0
- MAX_STRIKE_GAP_STEPS = 10
- SNAPSHOT_SCHEDULE = 每日 **北京时间 16:05** 生成 `dt=YYYY-MM-DD` 分区

---

## 十四、验收标准

- 首启成功：`data/parquet/dt=YYYY-MM-DD` 存在，`/api/meta/dates` 返回该日期
- 每日定时：16:05（UTC+8）后能够生成当日 `dt=...` 分区，并自动成为默认查询日期
- `GET /api/meta/asof` 返回正确的 `asof_ts` 与来源
- `POST /api/spread/scan` 返回四类策略的 Top/Bottom 结果
- 前端能显示“数据更新于 …”并基于选择日期展示结果

---
