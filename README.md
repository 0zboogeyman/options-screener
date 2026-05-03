# 期权策略推荐系统 (Option Strategy Finder)

基于 Deribit 期权数据的智能期权策略筛选工具，支持价差策略（Spread）和单腿策略（CSP/CC），通过多维度过滤机制推荐高质量的期权交易机会。

![SignalPlus](https://signalplus.com/logo.png)

## 📋 功能特性

### 🎯 核心功能
- **价差策略筛选**：自动分析并推荐最优期权价差组合（看涨/看跌，借方/贷方）
- **CSP 策略（打折买币）**：现金备兑看跌期权，以折扣价接入现货
- **CC 策略（加钱卖货）**：现货备兑看涨期权，持有现货基础上卖出看涨获取额外收益
- **双层过滤机制**：确保数据质量，过滤噪声数据
- **实时数据更新**：基于 Deribit 每日期权链快照
- **多维度展示**：支持四种价差策略类型 + 两种单腿策略

### 🔍 数据过滤规则

#### 价差策略过滤

**第一层：单腿期权过滤**
- **spread_ratio > 0.5**：过滤买卖价差超过中间价 50% 的期权
- 确保每个期权都有合理的流动性
- 避免深度虚值期权的报价噪声

**第二层：组合过滤**
- **权利金 < $10**：过滤权利金过小的价差组合
- 避免深度虚值期权组合导致的极端赔率
- 提升策略推荐的可操作性

#### 单腿策略过滤

**CSP 策略（打折买币）**
- Delta 限制：控制行权概率
- 持仓量（OI）：确保流动性
- 买卖价差（Spread）：控制交易成本
- 可用资金：匹配保证金要求

**CC 策略（加钱卖货）**
- Delta 限制：控制被行权风险
- 持仓量（OI）：确保流动性
- 买卖价差（Spread）：控制交易成本
- 持仓数量：计算策略收益

### 📊 策略类型

#### 价差策略（Spread）

**看涨期权价差**
- **借方价差（DEBIT）**：小成本博取大回报 - Top 3 高赔率策略
- **贷方价差（CREDIT）**：最具性价比的鸭子策略 - Bottom 3 低赔率策略

**看跌期权价差**
- **借方价差（DEBIT）**：小成本博取大回报 - Top 3 高赔率策略
- **贷方价差（CREDIT）**：最具性价比的鸭子策略 - Bottom 3 低赔率策略

#### 单腿策略（Single Leg）

**CSP - 打折买币（现金备兑看跌）**
- 策略说明：卖出看跌期权，以低于当前价格接入现货，同时赚取权利金
- 适用场景：看多但希望以更低价格建仓
- 关键指标：
  - **上涨空间%**：当前价格到行权价的涨幅空间
  - **APR**：年化收益率（基于名义本金）
  - **行权概率**：基于 Delta 估算的被行权概率

**CC - 加钱卖货（现货备兑看涨）**
- 策略说明：持有现货基础上卖出看涨期权，获取额外权利金收益
- 适用场景：持有现货，预期短期震荡或小幅上涨
- 关键指标：
  - **上涨空间%**：当前价格到行权价的涨幅空间
  - **APR**：年化收益率（基于名义本金）
  - **行权概率**：基于 Delta 估算的被行权概率

### 💡 智能特性
- **自动到期日选择**：默认选择距离一周的到期日
- **剩余天数显示**：直观展示期权剩余时间（DTE）
- **虚值期权筛选**：自动过滤实值期权（ITM），只保留虚值和平值
- **Delta 估算**：基于 moneyness 的分段函数准确估算期权 Delta
- **全局数据展示**：统一显示数据时间、现货价格、DVOL 指数
- **中文界面**：全中文界面，易于理解
- **北京时间**：数据时间采用北京时区

## 🏗️ 技术架构

### 后端 (Backend)
- **框架**：FastAPI + Python 3.12
- **数据处理**：Pandas + NumPy
- **期权定价**：Black-Scholes 模型
- **数据存储**：Parquet 格式快照

**主要组件**：
```
backend/
├── app/
│   ├── api/               # API 路由
│   │   ├── routes_meta.py       # 元数据接口
│   │   ├── routes_spread.py     # 价差策略接口
│   │   └── routes_single_leg.py # 单腿策略接口
│   ├── services/          # 业务逻辑
│   │   ├── scanner.py          # 价差扫描引擎
│   │   ├── single_leg.py       # 单腿策略引擎
│   │   ├── loader.py           # 数据加载
│   │   └── bs.py               # BS 模型计算
│   └── main.py            # 应用入口
└── data/                  # 期权链快照数据
```

### 前端 (Frontend)
- **框架**：Next.js 14.2.3 + React
- **语言**：TypeScript
- **部署**：Standalone 模式
- **基础路径**：/option-strategy-finder

**主要组件**：
```
frontend/
├── pages/
│   └── index.tsx              # 主页面（多标签界面）
├── components/
│   ├── ResultBucket.tsx       # 价差策略展示组件
│   ├── CSPScanner.tsx         # CSP 策略扫描组件
│   └── CCScanner.tsx          # CC 策略扫描组件
├── public/                    # 静态资源
└── build.sh                   # 构建脚本
```

## 📐 计算公式

### 价差策略赔率计算
```
赔率 = |K2 - K1| / (权利金 × 现货价格)
```
保留 1 位小数

### 借方价差
```
最大收益 = |K2 - K1| (金本位 USD)
最大亏损 = 权利金 (币本位)
```

### 贷方价差
```
最大收益 = 权利金 (币本位)
最大亏损 = |K2 - K1| (金本位 USD)
```

### 单腿策略计算

**CSP 策略**
```
折扣幅度 = (现货价格 - 行权价) / 现货价格
年化收益率 = (权利金 / 保证金要求) × (365 / DTE)
行权概率 = |Delta| (看跌期权 Delta 为负)
综合得分 = APR × 0.4 + (1-行权概率) × 0.3 + 流动性评分 × 0.3
```

**CC 策略**
```
上涨空间 = (行权价 - 现货价格) / 现货价格
年化收益率 = (权利金 / (现货价格 × 持仓量)) × (365 / DTE)
行权概率 = Delta (看涨期权 Delta 为正)
综合得分 = APR × 0.4 + (1-行权概率) × 0.3 + 流动性评分 × 0.3
```

### spread_ratio 计算
```
spread_ratio = (ask - bid) / mid_price
```
- 0 ~ 0.2：流动性好
- 0.2 ~ 0.5：流动性一般
- > 0.5：流动性差（过滤）

### Delta 估算（单腿策略）

**看跌期权（CSP）**
```
moneyness = strike / spot
if moneyness < 0.9:      # Deep OTM
    delta = -0.1 × (moneyness / 0.9)
elif moneyness < 1.0:    # Slightly OTM
    delta = -0.1 - 0.4 × ((moneyness - 0.9) / 0.1)
elif moneyness < 1.1:    # Slightly ITM
    delta = -0.5 - 0.4 × ((moneyness - 1.0) / 0.1)
else:                    # Deep ITM
    delta = -0.9 - 0.09 × min((moneyness - 1.1), 1.0)
```

**看涨期权（CC）**
```
moneyness = strike / spot
if moneyness > 1.1:      # Deep OTM
    delta = 0.1 × (1.1 / moneyness)
elif moneyness > 1.0:    # Slightly OTM
    delta = 0.1 + 0.4 × ((1.1 - moneyness) / 0.1)
elif moneyness > 0.9:    # Slightly ITM
    delta = 0.5 + 0.4 × ((1.0 - moneyness) / 0.1)
else:                    # Deep ITM
    delta = 0.9 + 0.09 × min((0.9 - moneyness) / 0.1, 1.0)
```

## 🚀 部署指南

### 环境要求
- Python 3.12+
- Node.js 18+
- PM2（进程管理）
- Tailscale（网络访问）

### 后端部署
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 获取 Tailscale IP
TS_IP=$(tailscale ip -4 | head -n1)

# 使用 PM2 启动（绑定到 Tailscale IP）
pm2 start "uvicorn app.main:app --host ${TS_IP} --port 3115" --name spread-finder-api
pm2 save
```

### 前端部署
```bash
cd frontend

# 使用构建脚本（自动化构建和部署）
chmod +x build.sh
./build.sh

# 或手动构建
npm install
npm run build

# 复制静态文件到 standalone
cp -r .next/static .next/standalone/.next/
cp -r public .next/standalone/

# 获取 Tailscale IP
TS_IP=$(tailscale ip -4 | head -n1)

# 使用 PM2 启动
pm2 start "node .next/standalone/server.js" --name spread-finder-web -- --hostname ${TS_IP} --port 3101
pm2 save
```

### 反向代理配置（Caddy）

需要管理员在 `/etc/caddy/sites/kunkka.conf` 中添加以下配置：

```caddy
# 前端服务
handle /option-strategy-finder* {
    reverse_proxy 100.103.163.38:3101
}

# 后端 API
handle /option-strategy-finder/api* {
    reverse_proxy 100.103.163.38:3115
}
```

配置后重载 Caddy：
```bash
sudo systemctl reload caddy
```

详细说明见项目根目录的 `CADDY_UPDATE_REQUIRED.md` 文件。

## 📊 数据流程

### 价差策略数据流
```
Deribit API
    ↓
每日快照 (Parquet)
    ↓
数据加载与预处理
    ↓
spread_ratio 过滤 (> 0.5)
    ↓
虚值期权筛选 (OTM/ATM)
    ↓
价差组合计算
    ↓
权利金过滤 (< $10)
    ↓
赔率排序 (Top/Bottom)
    ↓
前端展示
```

### 单腿策略数据流
```
Deribit API
    ↓
每日快照 (Parquet)
    ↓
数据加载与预处理
    ↓
spread_ratio 过滤
    ↓
Delta 估算（moneyness-based）
    ↓
Delta/OI/DTE 筛选
    ↓
收益率计算（APR）
    ↓
综合评分排序
    ↓
前端展示
```

## 🎨 界面示例

### 主页面布局
- **顶部**：SignalPlus Logo + 系统标题
- **全局数据区**：数据时间（北京时间）| 现货价格 | DVOL 指数
- **标签页导航**：Opinion | Expiry | CSP 打折买币 | CC 加钱卖货
- **策略展示**：根据选中标签显示对应策略

### Opinion 标签（看涨/看跌）
- **控制面板**：标的资产 | 数据日期
- **策略卡片**：4 个策略类型（看涨借方/贷方，看跌借方/贷方）
- **表格列**：执行价 1 | 执行价 2 | 权利金🛈 | 最大收益 | 最大亏损 | 赔率

### Expiry 标签（按到期日）
- **控制面板**：标的资产 | 数据日期 | 到期日选择
- **策略卡片**：4 个策略类型
- **DTE 显示**：自动显示剩余天数

### CSP 打折买币标签
- **筛选器**：标的 | 最大DTE | 最大Delta | 持仓合约数量 | 最小持仓量 | 最大点差
- **表格列**：合约 | 到期日 | 行权价 | Delta | 权利金 | 上涨空间% | APR | 行权概率 | 持仓量 | 得分
- **扫描按钮**：触发策略扫描并更新全局数据

### CC 加钱卖货标签
- **筛选器**：标的 | 最大DTE | 最大Delta | 可用资金 | 最小持仓量 | 最大点差
- **表格列**：合约 | 到期日 | 行权价 | Delta | 权利金 | 上涨空间% | APR | 行权概率 | 持仓量 | 得分
- **扫描按钮**：触发策略扫描并更新全局数据

### 提示信息
鼠标悬停在权利金🛈图标上：
```
数据过滤规则：
1. 过滤单腿期权 spread_ratio > 0.5（买卖价差超过中间价50%）
2. 过滤组合权利金 < $10（避免深度虚值期权）
```

## 🔧 API 接口

### 元数据接口
- `GET /api/meta/bases` - 获取支持的标的资产列表
- `GET /api/meta/dates` - 获取可用的数据日期列表
- `GET /api/meta/expiries` - 获取指定标的的到期日列表

### 价差策略接口
- `POST /api/spread/by-opinion` - 按看涨/看跌筛选策略
- `POST /api/spread/by-expiry` - 按到期日筛选策略

### 单腿策略接口
- `POST /api/strategy/csp` - CSP 策略扫描
- `POST /api/strategy/cc` - CC 策略扫描

所有接口同时支持 `/api` 和 `/option-strategy-finder/api` 两种路径。

## ⚠️ 免责声明

**仅教育用途，非投资建议，数据来源于 Deribit**

本工具仅用于期权策略的学习和研究，不构成任何投资建议。期权交易具有高风险，可能导致全部本金损失。使用本工具进行交易决策的风险由用户自行承担。

## 📝 更新日志

### v4.0.0 (2026-05-03)
- 📱 **优化手机移动客户端兼容性**：全面适配移动端，修复布局错乱、触控目标过小、表格滚动等问题
- 🌐 **在线演示**：https://option.311472.xyz/
- 🎨 **界面视觉升级**：金色主题设计，暗黑模式优化，卡片悬停动效
- 🌓 **新增主题切换**：支持明亮/暗黑模式，自动保存用户偏好
- ✨ **交互体验优化**：Toast 提示替代 alert，加载动画，按钮微交互
- 🔗 **页脚信息完善**：标注原作者 Kunkka 及二次开发者信息

### v3.0.0 (2025-10-12)
- ✨ 新增 CSP（打折买币）和 CC（加钱卖货）单腿策略
- 🎯 改进 Delta 估算算法，使用基于 moneyness 的分段函数
- 🎨 添加多标签界面（Opinion/Expiry/CSP/CC）
- 📊 实现全局数据展示（数据时间/现货价格/DVOL指数）
- 🔄 项目路径从 `/spread-finder` 迁移到 `/option-strategy-finder`
- 🚀 添加自动化构建脚本
- 📐 新增单腿策略综合评分系统

### v2.0.0 (2025-10-05)
- ✨ 添加双层过滤机制（spread_ratio + 权利金）
- 🎨 界面全面中文化
- 🔧 修正借方/贷方计算公式
- 📊 添加 Top/Bottom 标识
- 🛈 添加过滤规则提示
- 📄 添加免责声明

### v1.0.0 (2025-10-03)
- 🎉 初始版本发布
- 🔍 基础价差扫描功能
- 📊 四种策略类型支持
- 🌐 Next.js + FastAPI 架构

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系方式

- **原作者项目**：https://github.com/xiaochongkun/option-strategy-finder
- **二次开发 Fork**：https://github.com/0zBoogeyman/option-strategy-finder
- **在线演示**：https://option.311472.xyz/
- **SignalPlus**：https://signalplus.com

## 📄 License

MIT License

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
