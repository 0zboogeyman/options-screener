"""API 安全层回归测试。

覆盖：
  SEC-1   prod 下未配置 ADMIN_TOKEN 时管理端点 403
  SEC-3   限流 key / 客户端 IP 解析：仅受信代理才信任 XFF/X-Real-IP
  SEC-4   请求体大小限制返回 413
  E-3     date 参数日历合法性校验返回 422
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes_etl import _check_admin_token
from app.core import ratelimit
from app.core.config import settings
from app.main import app


class _Headers(dict):
    """大小写不敏感的头字典（模拟 starlette Headers 行为）。"""

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Req:
    """最小 Request 桩：headers 大小写不敏感。"""

    def __init__(self, headers=None, client_host="10.0.0.1"):
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.client = type("C", (), {"host": client_host})()


class TestAdminTokenPolicy:
    """审计 SEC-1：prod 下空 token 403，dev 下放行。"""

    def test_prod_without_token_403(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_token", "")
        monkeypatch.setattr(settings, "env", "prod")
        with pytest.raises(HTTPException) as ei:
            _check_admin_token(_Req())
        assert ei.value.status_code == 403

    def test_dev_without_token_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_token", "")
        monkeypatch.setattr(settings, "env", "dev")
        _check_admin_token(_Req())  # 不抛

    def test_wrong_token_401(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_token", "correct")
        monkeypatch.setattr(settings, "env", "prod")
        with pytest.raises(HTTPException) as ei:
            _check_admin_token(_Req(headers={"X-Admin-Token": "wrong"}))
        assert ei.value.status_code == 401

    def test_correct_token_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_token", "correct")
        _check_admin_token(_Req(headers={"X-Admin-Token": "correct"}))


class TestResolveClientIp:
    """审计 SEC-3：XFF 仅在受信代理场景被信任。"""

    def test_direct_connection_ignores_xff(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", [])
        monkeypatch.setattr(ratelimit, "_trusted_nets", None)
        req = _Req(headers={"X-Forwarded-For": "9.9.9.9"}, client_host="10.0.0.1")
        assert ratelimit.resolve_client_ip(req) == "10.0.0.1"

    def test_trusted_proxy_uses_xff(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1"])
        monkeypatch.setattr(ratelimit, "_trusted_nets", None)
        req = _Req(headers={"X-Forwarded-For": "9.9.9.9"}, client_host="127.0.0.1")
        assert ratelimit.resolve_client_ip(req) == "9.9.9.9"

    def test_trusted_cidr_range(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", ["172.16.0.0/12"])
        monkeypatch.setattr(ratelimit, "_trusted_nets", None)
        req = _Req(headers={"X-Forwarded-For": "8.8.8.8"}, client_host="172.17.0.1")
        assert ratelimit.resolve_client_ip(req) == "8.8.8.8"

    def test_invalid_xff_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1"])
        monkeypatch.setattr(ratelimit, "_trusted_nets", None)
        req = _Req(headers={"X-Forwarded-For": "not-an-ip"}, client_host="127.0.0.1")
        assert ratelimit.resolve_client_ip(req) == "127.0.0.1"


class TestHttpContract:
    """HTTP 层行为：413 body 限制 / 422 日历校验。"""

    def test_oversized_body_413(self):
        client = TestClient(app)
        big_body = {"base": "BTC", "date": "2026-08-06", "direction": "both",
                    "tenor": "near", "pad": "x" * (2 * 1024 * 1024)}
        resp = client.post("/api/spread/scan", json=big_body)
        assert resp.status_code == 413

    def test_invalid_calendar_date_422(self):
        client = TestClient(app)
        resp = client.post("/api/spread/scan", json={
            "base": "BTC", "date": "2026-99-99", "direction": "both", "tenor": "near",
        })
        assert resp.status_code == 422

    def test_health_ok(self):
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
