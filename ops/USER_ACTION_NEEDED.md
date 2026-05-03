# ⚠️ 需要用户操作：配置 Caddy 反向代理

## 当前状态

✅ **后端服务**: 正常运行
✅ **前端服务**: 正常运行
✅ **数据 ETL**: 已配置定时任务
❌ **外部访问**: 404（Caddy 配置缺失）

---

## 问题原因

**Caddy 反向代理配置未添加**，导致外部访问 `https://kunkka.spailab.com/spread-finder` 返回 404。

根据你的环境说明文档（`~/.claude/CLAUDE.md`）：
> 入口网关：域名 https://kunkka.spailab.com 的配置
> - 反向代理配置在 /etc/caddy/sites（**需管理员修改**）

---

## 需要你做什么

### 方案 A: 联系管理员配置（推荐）

**1. 准备好的配置文档**：
- 详细配置说明: `ops/CADDY_SETUP_REQUEST.md`
- 配置参考: `ops/CADDY_CONFIG.md`

**2. 需要管理员添加的配置**：
```caddy
handle /spread-finder* {
    reverse_proxy 127.0.0.1:3000
}
```

**3. 联系方式**：
根据你的环境，联系管理员并提供以上配置文档。

---

### 方案 B: 自己配置（如果你有 sudo 权限）

如果你有管理员权限，可以自己操作：

```bash
# 1. 查找 Caddy 配置文件
sudo find /etc/caddy -name "*.conf" -o -name "Caddyfile"

# 2. 编辑配置文件（假设是 /etc/caddy/Caddyfile）
sudo nano /etc/caddy/Caddyfile

# 3. 在 kunkka.spailab.com 块中添加：
#    handle /spread-finder* {
#        reverse_proxy 127.0.0.1:3000
#    }

# 4. 验证配置语法
sudo caddy validate --config /etc/caddy/Caddyfile

# 5. 重载配置
sudo systemctl reload caddy

# 6. 验证生效
curl -I https://kunkka.spailab.com/spread-finder
```

---

## 验证配置成功

配置完成后，运行以下命令验证：

```bash
# 测试 1: 页面访问
curl -I https://kunkka.spailab.com/spread-finder
# 预期: HTTP/2 200

# 测试 2: API 健康检查
curl https://kunkka.spailab.com/spread-finder/api/health
# 预期: {"status":"ok"}

# 测试 3: 浏览器访问
# 打开 https://kunkka.spailab.com/spread-finder
# 确认页面正常显示
```

---

## 配置完成后

✅ 项目即可正式上线！

访问地址: **https://kunkka.spailab.com/spread-finder**

功能验证:
1. 选择标的（BTC/ETH）
2. 选择方向（up/down）和到期档位（near/mid/far）
3. 系统自动扫描并显示价差策略
4. 查看赔率（odds）、盈利概率（POP）等指标

---

## 临时测试方法（无需 Caddy）

如果等待管理员配置期间想要测试，可以使用 SSH 隧道：

```bash
# 在本地电脑运行
ssh -L 8080:127.0.0.1:3000 kunkka@<server-ip>

# 然后在浏览器访问
http://localhost:8080/spread-finder
```

**注意**: 此方法仅供临时测试，不能作为生产环境方案。

---

## 帮助与支持

如有问题，查看以下文档：
- `ops/CADDY_SETUP_REQUEST.md` - 管理员配置请求
- `ops/CADDY_CONFIG.md` - 详细配置说明
- `ops/DEPLOYMENT_REPORT.md` - 部署完成报告
- `ops/PM2_ECOSYSTEM.md` - 服务管理指南

检查服务状态：
```bash
pm2 list | grep spread-finder
pm2 logs spread-finder
```

---

**当前任务**: 等待 Caddy 配置 → 然后项目即可上线 🚀
