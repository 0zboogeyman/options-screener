"""应用级限流器与客户端 IP 解析（审计 SEC-3 / SEC-7）。

slowapi 默认的 get_remote_address 只取 request.client.host，在反代 + docker
端口映射下恒为网关 IP，所有客户端共享同一配额（互相 429 / 可被刷满全站 DoS）。
这里提供统一的客户端 IP 解析：

  * 仅当请求对端命中 settings.trusted_proxies（IP 或 CIDR）时，才信任
    X-Forwarded-For 首段 / X-Real-IP 头——伪造代理头在直连场景无效；
  * 对端不受信或头部缺失/非法时回退 request.client.host（直连场景即真实 IP）。

routes_geo 的 _client_ip 与本函数共用该解析，保证限流与 geo 识别口径一致。
"""
from __future__ import annotations

import ipaddress
import threading
from typing import List, Optional

from slowapi import Limiter
from slowapi.util import get_remote_address  # noqa: F401 (re-export 兼容)

from .config import settings

# 编译后的受信代理网络列表（线程安全惰性初始化）
_trusted_nets: Optional[List] = None
_trusted_nets_lock = threading.Lock()


def _compiled_trusted() -> List:
    """将 settings.trusted_proxies 编译为 ipaddress 网络对象（支持 CIDR）。"""
    global _trusted_nets
    if _trusted_nets is not None:
        return _trusted_nets
    with _trusted_nets_lock:
        if _trusted_nets is None:
            nets: List = []
            for raw in settings.trusted_proxies:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    nets.append(ipaddress.ip_network(raw, strict=False))
                except ValueError:
                    try:
                        nets.append(ipaddress.ip_network(ipaddress.ip_address(raw)))
                    except ValueError:
                        continue
            _trusted_nets = nets
    return _trusted_nets


def _valid_ip(value: str) -> str:
    """严格 IP 格式校验，非法值返回空串（防伪造头注入）。"""
    value = value.strip()
    if not value:
        return ""
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return ""


def resolve_client_ip(request) -> str:
    """解析客户端真实 IP：仅受信代理场景信任 XFF/X-Real-IP。

    返回 request.client.host 当：无受信代理、头缺失、或头值非法。
    """
    peer = request.client.host if request.client else ""
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        peer_ip = None

    trusted = _compiled_trusted()
    if peer_ip is not None and trusted and any(peer_ip in net for net in trusted):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",")[0].strip()
            valid = _valid_ip(first)
            if valid:
                return valid
        xri = request.headers.get("x-real-ip", "")
        if xri:
            valid = _valid_ip(xri)
            if valid:
                return valid
    return peer


def _key_func(request) -> str:
    return resolve_client_ip(request)


# 全应用共享的限流器实例，限流阈值统一从 settings 读取，
# 避免各路由模块各自实例化导致配置漂移。
limiter = Limiter(key_func=_key_func)
