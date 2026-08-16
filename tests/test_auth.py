# -*- coding: utf-8 -*-
"""认证接口测试：正确/错误/格式错 OTP、未授权拒绝、登出吊销。"""
from helpers import req, make_otp


def test_login_ok(token):
    assert isinstance(token, str) and len(token) > 0


def test_login_wrong_otp():
    status, _ = req("POST", "/api/auth/login", {"otp": "000000"})
    assert status == 403


def test_login_bad_format():
    for bad in ["123", "abcdef", "1234567", "12 34", ""]:
        status, _ = req("POST", "/api/auth/login", {"otp": bad})
        assert status == 400, f"格式非法 {bad!r} 应返回 400，实际 {status}"


def test_unauth_rejected():
    status, _ = req("GET", "/api/alerts?limit=10")
    assert status == 401


def test_logout_revokes():
    # 用独立令牌测试吊销，避免污染共享会话令牌
    otp = make_otp()
    s0, data = req("POST", "/api/auth/login", {"otp": otp})
    assert s0 == 200
    t2 = data["token"]
    s1, _ = req("GET", "/api/alerts?limit=10", token=t2)
    assert s1 == 200
    s2, _ = req("POST", "/api/auth/logout", headers={"Authorization": f"Bearer {t2}"})
    assert s2 == 200
    s3, _ = req("GET", "/api/alerts?limit=10", token=t2)
    assert s3 == 401
