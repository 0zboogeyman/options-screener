from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# 全应用共享的限流器实例，限流阈值统一从 settings 读取，
# 避免各路由模块各自实例化导致配置漂移。
limiter = Limiter(key_func=get_remote_address)
