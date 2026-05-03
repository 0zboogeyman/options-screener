# Spread Finder - Caddy 反向代理配置请求

## 问题诊断

**当前状态**：
- ✅ 后端服务正常运行：`127.0.0.1:3115`
- ✅ 前端服务正常运行：`127.0.0.1:3117` **（已更新为合规端口）**
- ❌ Caddy 配置缺失：未找到 `/spread-finder` 路由规则

**访问测试**：
```bash
# 本地访问正常
curl http://127.0.0.1:3117/spread-finder  # ✅ 200 OK
curl http://127.0.0.1:3115/api/health     # ✅ 200 OK

# 外部访问 404（Caddy 未配置）
curl https://kunkka.spailab.com/spread-finder  # ❌ 404 Not Found
```

---

## 配置请求

### 项目信息
- **项目名称**: Spread Finder（期权价差筛选器）
- **用户**: kunkka
- **项目路径**: `/home/kunkka/projects/spread-finder`
- **目标访问地址**: `https://kunkka.spailab.com/spread-finder`

### 服务端口
- **前端 (Next.js)**: `127.0.0.1:3117` **（合规端口范围 3101-3200）**
- **后端 (FastAPI)**: `127.0.0.1:3115` **（合规端口范围 3101-3200）**

---

## 需要添加的 Caddy 配置

请管理员在 Caddy 配置文件中添加以下规则：

### 配置方案 A：完整路径（推荐）

```caddy
# 在 kunkka.spailab.com 的配置块中添加

# Spread Finder - 期权价差筛选器
handle /spread-finder* {
    reverse_proxy 127.0.0.1:3117
}
```

### 配置说明
1. **路径匹配**: 使用 `handle /spread-finder*` 匹配所有子路径
2. **不使用 strip_prefix**: 保留完整路径传给 Next.js
3. **API 代理**: Next.js 已内置 rewrites，会自动将 `/spread-finder/api/*` 转发到后端
4. **优先级**: 确保此规则在其他通配符规则之前

### 完整配置示例

```caddy
kunkka.spailab.com {
    # 现有配置保持不变...

    # === 新增：Spread Finder ===
    handle /spread-finder* {
        reverse_proxy 127.0.0.1:3117
    }
    # === 新增结束 ===

    # 其他服务配置...

    # 默认 404（保持最后）
    handle {
        respond "Not Found" 404
    }
}
```

---

## 配置验证步骤

### 1. 添加配置后验证语法
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

### 2. 重载 Caddy 服务
```bash
sudo systemctl reload caddy
# 或
sudo systemctl restart caddy
```

### 3. 验证配置生效
```bash
# 方法 1: curl 测试
curl -I https://kunkka.spailab.com/spread-finder
# 预期: HTTP/2 200

# 方法 2: 检查 API
curl https://kunkka.spailab.com/spread-finder/api/health
# 预期: {"status":"ok"}

# 方法 3: 浏览器访问
# 打开 https://kunkka.spailab.com/spread-finder
```

### 4. 查看 Caddy 日志（如有问题）
```bash
sudo journalctl -u caddy -f
```

---

## 故障排查指南

### 问题 1: 仍然 404
**可能原因**:
- 配置未生效（未 reload）
- 路径匹配顺序问题
- 其他规则优先级更高

**解决方法**:
```bash
# 检查 Caddy 配置是否包含 spread-finder
sudo caddy adapt --config /etc/caddy/Caddyfile | grep -A 5 "spread-finder"

# 确认 reload 成功
sudo systemctl status caddy

# 查看实时日志
sudo journalctl -u caddy -f
```

### 问题 2: 502 Bad Gateway
**可能原因**:
- 前端服务未运行
- 端口号错误

**解决方法**:
```bash
# 检查服务状态
pm2 list | grep spread-finder-web

# 检查端口监听
netstat -tuln | grep 3000

# 手动测试本地访问
curl -I http://127.0.0.1:3000/spread-finder
```

### 问题 3: HTTPS 证书错误
**可能原因**:
- Let's Encrypt 证书自动获取失败

**解决方法**:
```bash
# 检查证书状态
sudo caddy list-certificates

# 强制重新获取证书（如需要）
sudo systemctl restart caddy
```

---

## 安全检查清单

配置完成后，请确认：

- [ ] 前端服务仅监听 `127.0.0.1:3000`（不是 0.0.0.0）
  ```bash
  netstat -tuln | grep 3000
  # 预期: 127.0.0.1:3000
  ```

- [ ] 后端服务仅监听 `127.0.0.1:3115`（不是 0.0.0.0）
  ```bash
  netstat -tuln | grep 3115
  # 预期: 127.0.0.1:3115
  ```

- [ ] 外部无法直接访问内部端口
  ```bash
  # 从外部机器测试（应该超时或拒绝）
  curl http://<server-ip>:3000 --max-time 5
  curl http://<server-ip>:3115 --max-time 5
  ```

- [ ] HTTPS 强制跳转生效
  ```bash
  curl -I http://kunkka.spailab.com/spread-finder
  # 预期: 301/302 跳转到 https://
  ```

---

## 配置后通知用户

配置完成后，请通知用户 kunkka：

**通知内容**:
```
✅ Spread Finder 反向代理已配置完成

访问地址: https://kunkka.spailab.com/spread-finder

验证方法:
1. 浏览器访问上述地址
2. 确认页面标题显示 "Spread Finder"
3. 选择参数后触发数据扫描
4. 确认结果正常显示

如有问题，请查看:
- 前端日志: pm2 logs spread-finder-web
- 后端日志: pm2 logs spread-finder-api
- Caddy 日志: sudo journalctl -u caddy -f
```

---

## 备用方案：直接端口映射（不推荐）

如果 Caddy 配置复杂，可临时使用 Tailscale 或 SSH 隧道：

```bash
# SSH 端口转发（临时测试）
ssh -L 8080:127.0.0.1:3000 kunkka@<server-ip>
# 然后访问 http://localhost:8080/spread-finder
```

**注意**: 此方案仅供测试，生产环境必须通过 Caddy 反代。

---

## 联系方式

**配置请求人**: kunkka
**请求时间**: 2025-10-03
**优先级**: P0（阻碍项目上线）

**配置文件位置**:
- 配置说明: `/home/kunkka/projects/spread-finder/ops/CADDY_CONFIG.md`
- 本请求文档: `/home/kunkka/projects/spread-finder/ops/CADDY_SETUP_REQUEST.md`

---

**感谢管理员支持！**
