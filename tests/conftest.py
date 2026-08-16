# -*- coding: utf-8 -*-
"""pytest 会话级夹具：登录拿令牌，供 API 测试复用。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from helpers import req, make_otp  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def otp() -> str:
    return make_otp()


@pytest.fixture(scope="session")
def token(otp: str) -> str:
    status, data = req("POST", "/api/auth/login", {"otp": otp})
    assert status == 200, f"登录失败: {status} {data}"
    assert "token" in data, f"响应缺少 token: {data}"
    return data["token"]


@pytest.fixture(scope="session")
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
