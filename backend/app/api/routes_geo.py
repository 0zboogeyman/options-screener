"""IP 地理位置识别端点。

调用 ip-api.com 免费版（HTTP only, 45 req/min, 无 key）：
  * 内存缓存按 IP 维度 TTL=7 天，避免同一 IP 重复消耗配额
  * single-flight 锁：同一 IP 并发只放行一个去调 ip-api，其余等待后读缓存，
    防缓存击穿（cache stampede）瞬时打爆 ip-api 配额
  * 进程级全局节流：剩余配额 ≤5 时静默返回默认语言，保护 ip-api 配额
  * 失败/超时/限流一律回退默认语言（zh-CN），前端无感
  * 不回显客户端 IP：仅返回 lang 供前端做语言跳转
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Request

from ..core.config import settings
from ..core.ratelimit import limiter, resolve_client_ip

logger = logging.getLogger(__name__)
router = APIRouter()

_GEO_RATE_LIMIT = "30/minute"

# 国家代码 → 语言映射（HK/MO/TW 是独立 ISO 3166-1 alpha-2，非 CN）
_COUNTRY_TO_LANG: Dict[str, str] = {
    "CN": "zh-CN",
    "HK": "zh-TW",
    "MO": "zh-TW",
    "TW": "zh-TW",
}

# 内存缓存（IP → (语言, 探测时间戳)）
_CACHE_TTL_SEC = 7 * 24 * 3600
_geo_cache: Dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()

# 全局节流：尊重 ip-api.com 的 X-Rl / X-Ttl 响应头
_throttle_until = 0.0
_throttle_lock = threading.Lock()
_IPAPI_TIMEOUT = 3.0

# single-flight：per-key 锁字典，保证同一 IP 同时只有一个 ip-api 调用
_inflight_locks: Dict[str, threading.Lock] = {}
_inflight_locks_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    """获取/创建某 IP 维度的 single-flight 锁。"""
    with _inflight_locks_guard:
        lock = _inflight_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _inflight_locks[key] = lock
        return lock


def _client_ip(request: Request) -> str:
    """解析客户端 IP（审计 SEC-7）：仅当对端命中 settings.trusted_proxies
    时才信任 XFF/X-Real-IP；直连场景一律取 request.client.host，
    防止伪造代理头污染缓存键 / 驱动外部 API 配额滥用。"""
    return resolve_client_ip(request)


def _is_throttled() -> bool:
    with _throttle_lock:
        return time.monotonic() < _throttle_until


def _update_throttle(remaining: int, ttl_sec: int) -> None:
    global _throttle_until
    if remaining <= 5:
        with _throttle_lock:
            _throttle_until = time.monotonic() + max(ttl_sec, 1)


def _lookup_ipapi(ip: str) -> str | None:
    """调 ip-api.com 解析国家代码 → 语言。失败返回 None。"""
    if not settings.geo_enabled:
        return None
    if _is_throttled():
        logger.info("geo: ip-api throttled, fallback to default lang")
        return None
    try:
        url = f"{settings.geo_ipapi_url}/{ip}"
        with httpx.Client(timeout=_IPAPI_TIMEOUT) as c:
            r = c.get(url, params={"fields": "status,message,countryCode,query"})
        if r.status_code == 429:
            _update_throttle(0, 60)
            logger.warning("geo: ip-api returned 429, throttling 60s")
            return None
        if r.status_code != 200:
            logger.warning("geo: ip-api status=%d", r.status_code)
            return None
        try:
            _update_throttle(
                int(r.headers.get("X-Rl", "999")),
                int(r.headers.get("X-Ttl", "60")),
            )
        except ValueError:
            pass
        data = r.json()
        if data.get("status") != "success":
            logger.info("geo: ip-api fail for %s: %s", ip, data.get("message"))
            return None
        cc = (data.get("countryCode") or "").upper()
        return _COUNTRY_TO_LANG.get(cc, "en")
    except Exception as exc:
        logger.warning("geo: ip-api call failed: %s", exc)
        return None


def _resolve_lang(ip: str) -> str:
    """带 IP 维度缓存 + single-flight 防击穿的解析入口。"""
    if not ip:
        return settings.geo_default_lang
    now = time.monotonic()
    with _cache_lock:
        hit = _geo_cache.get(ip)
        if hit and now - hit[1] < _CACHE_TTL_SEC:
            return hit[0]
    # single-flight：同一 IP 并发只放行一个去调 ip-api，其余等待后读缓存
    key_lock = _key_lock(ip)
    with key_lock:
        # double-check：等待期间可能已被其他请求填充
        now = time.monotonic()
        with _cache_lock:
            hit = _geo_cache.get(ip)
            if hit and now - hit[1] < _CACHE_TTL_SEC:
                return hit[0]
        lang = _lookup_ipapi(ip) or settings.geo_default_lang
        with _cache_lock:
            _geo_cache[ip] = (lang, time.monotonic())
            if len(_geo_cache) > 10000:
                sorted_items = sorted(_geo_cache.items(), key=lambda kv: kv[1][1])
                _geo_cache.clear()
                _geo_cache.update(dict(sorted_items[len(sorted_items) // 2:]))
                # 同步清理 single-flight 锁字典，防止无界增长
                with _inflight_locks_guard:
                    _inflight_locks.clear()
    return lang


@router.get("/geo")
@limiter.limit(_GEO_RATE_LIMIT)
def get_geo(request: Request) -> Dict[str, Any]:
    ip = _client_ip(request)
    lang = _resolve_lang(ip)
    source = "disabled" if not settings.geo_enabled else ("cache" if ip in _geo_cache else "ip-api.com")
    # 注意：不回显客户端 IP。前端仅消费 lang 做语言跳转，无需 IP；
    # 回显 IP 是不必要的隐私反射面（可被脚本探测访客 IP）。
    return {"lang": lang, "source": source}
