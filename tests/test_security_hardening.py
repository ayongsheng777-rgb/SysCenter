# -*- coding: utf-8 -*-
"""生产级加固验证：Redis 会话角色、统一错误格式、请求 ID、审计日志。"""
import urllib.request

from helpers import BASE, req, make_otp


def test_login_returns_role():
    otp = make_otp()
    status, data = req("POST", "/api/auth/login", {"otp": otp})
    assert status == 200
    assert data.get("role") == "admin"
    assert data.get("token")


def test_error_schema_401():
    status, data = req("GET", "/api/alerts?limit=10")
    assert status == 401
    assert data.get("success") is False
    assert data.get("code") == "AUTH_REQUIRED"
    assert data.get("message")
    assert data.get("request_id")


def test_error_schema_404(token):
    status, data = req("DELETE", "/api/vps/999999", token=token)
    assert status == 404
    assert data.get("success") is False
    assert data.get("code") == "NOT_FOUND"
    assert data.get("request_id")


def test_request_id_header_present():
    reqobj = urllib.request.Request(BASE + "/api/ping")
    with urllib.request.urlopen(reqobj, timeout=10) as r:
        assert r.headers.get("X-Request-ID"), "响应缺少 X-Request-ID 头"


def test_audit_log_records_login(token):
    status, data = req("GET", "/api/audit?limit=200", token=token)
    assert status == 200
    assert any(r["action"] == "login" for r in data)


def test_audit_requires_auth():
    status, data = req("GET", "/api/audit")
    assert status == 401
