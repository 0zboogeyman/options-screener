# Caddy 反向代理配置更新说明

## 域名路径变更

项目的 URL 路径已从 `/spread-finder` 更改为 `/option-strategy-finder`

## 需要管理员更新的配置

请管理员更新 Caddy 配置文件（`/etc/caddy/sites/kunkka.conf` 或类似文件），将以下配置：

### 旧配置（需要移除或注释）

```caddy
handle /spread-finder* {
    reverse_proxy 100.103.163.38:3101
}

handle /spread-finder/api* {
    reverse_proxy 100.103.163.38:3115
}
```

### 新配置（需要添加）

```caddy
handle /option-strategy-finder* {
    reverse_proxy 100.103.163.38:3101
}

handle /option-strategy-finder/api* {
    reverse_proxy 100.103.163.38:3115
}
```

## 服务端口

- **前端服务**: `100.103.163.38:3101`
- **后端 API**: `100.103.163.38:3115`

## 更新后重载 Caddy

```bash
sudo systemctl reload caddy
```

## 验证访问

更新配置后，请访问以下 URL 验证：
- 前端页面: `https://kunkka.spailab.com/option-strategy-finder/`
- API 健康检查: `https://kunkka.spailab.com/option-strategy-finder/api/health`

## 已更新的应用配置

以下配置已在应用层面更新完成：
- ✅ Next.js basePath: `/option-strategy-finder`
- ✅ 前端 API_BASE: `/option-strategy-finder/api`
- ✅ 后端路由前缀: `/option-strategy-finder/api`
- ✅ 前端已重新构建并部署
- ✅ 后端服务已重启

只需要管理员更新 Caddy 反向代理配置即可完成整个迁移。
