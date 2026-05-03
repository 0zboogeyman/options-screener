# Caddy 反向代理配置说明

## 项目访问信息

- **项目名称**: Spread Finder (期权价差筛选器)
- **项目路径**: `/home/kunkka/projects/spread-finder`
- **对外访问**: `https://kunkka.spailab.com/spread-finder`

## 服务端口信息

### 本地服务端口（仅监听 127.0.0.1）
- **前端 (Next.js)**: 127.0.0.1:3000
- **后端 (FastAPI)**: 127.0.0.1:3115

### PM2 进程管理
```bash
pm2 list | grep spread-finder
# spread-finder-api    - 后端 API 服务
# spread-finder-web    - 前端 Web 服务
# spread-finder-etl    - ETL 定时任务（北京时间 16:05）
```

## Caddy 配置片段

请管理员添加以下配置到 `/etc/caddy/sites/kunkka.conf`:

```caddy
# Spread Finder - 期权价差筛选器
handle /spread-finder* {
    # 前端静态资源和页面
    reverse_proxy 127.0.0.1:3000
}
```

## 配置说明

### 1. 路径处理
- 使用 `handle /spread-finder*` 匹配所有以 `/spread-finder` 开头的路径
- **不使用** `handle_path` 或 `strip_prefix`，保留完整路径传给 Next.js
- Next.js 已配置 `basePath: "/spread-finder"`，会自动处理子路径

### 2. API 代理
- 前端内置了 API 代理 (Next.js rewrites)
- 浏览器请求 `https://kunkka.spailab.com/spread-finder/api/*`
- Next.js 会自动转发到后端 `http://127.0.0.1:3115/api/*`
- 无需在 Caddy 层面单独配置 API 路由

### 3. 安全设置
- 所有服务仅监听 `127.0.0.1`，不暴露到外网
- 仅通过 Caddy 统一入口访问
- SSL 证书由 Caddy 自动管理

## 配置应用步骤

1. **编辑配置文件**
   ```bash
   sudo nano /etc/caddy/sites/kunkka.conf
   ```

2. **添加上述配置片段**
   在现有配置中添加 `handle /spread-finder*` 块

3. **验证配置语法**
   ```bash
   sudo caddy validate --config /etc/caddy/Caddyfile
   ```

4. **重载配置**
   ```bash
   sudo systemctl reload caddy
   ```

## 验证方法

配置完成后，可以通过以下方式验证：

```bash
# 检查前端访问
curl -I https://kunkka.spailab.com/spread-finder

# 检查 API 访问（通过前端代理）
curl https://kunkka.spailab.com/spread-finder/api/health
# 应返回: {"status":"ok"}

# 检查日期列表接口
curl https://kunkka.spailab.com/spread-finder/api/meta/dates
# 应返回: {"dates":["2025-10-03"]}
```

## 故障排查

### 404 错误
- 检查 PM2 服务是否运行: `pm2 list | grep spread-finder`
- 检查端口是否监听: `netstat -tuln | grep -E '3000|3115'`

### 502 Bad Gateway
- 检查后端服务健康: `curl http://127.0.0.1:3115/api/health`
- 检查前端服务: `curl http://127.0.0.1:3000/spread-finder`

### API 调用失败
- 检查浏览器 Network 面板，确认请求路径
- 检查后端日志: `pm2 logs spread-finder-api`

## 联系方式

如有问题，请联系管理员配置或查看 Caddy 日志：
```bash
sudo journalctl -u caddy -f
```

---

**配置日期**: 2025-10-03
**维护人员**: kunkka
