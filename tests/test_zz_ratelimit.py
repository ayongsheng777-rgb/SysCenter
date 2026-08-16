# -*- coding: utf-8 -*-
"""登录限速（放最后执行：会临时锁定本机 IP，测试后重启后端即可清除）。

连续错误 OTP 应触发 429 锁定；所有响应只能是 403 或 429。
"""
from helpers import req


def test_login_rate_limit():
    codes = []
    for _ in range(7):
        s, _ = req("POST", "/api/auth/login", {"otp": "111111"})
        codes.append(s)
    assert 429 in codes, f"应触发锁定 429，实际 {codes}"
    assert all(c in (403, 429) for c in codes), f"出现非预期状态码 {codes}"
