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
- 每日或每日两次抓取 BTC/ETH 全链快照
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

# Spread Finder Backend\nSee spread-finder-design.md for full spec.
