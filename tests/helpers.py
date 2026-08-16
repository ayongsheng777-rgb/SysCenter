# -*- coding: utf-8 -*-
"""测试辅助：HTTP 客户端（标准库 urllib，无第三方依赖）+ OTP 生成。

指向运行中的后端（默认 http://127.0.0.1:8352，可用 TEST_BASE_URL 覆盖）。
"""
import os
import sys
import time
import json
import urllib.request
import urllib.error

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8352").rstrip("/")


def req(method: str, path: str, data=None, headers=None, token: str | None = None):
    """发起 HTTP 请求，返回 (status, json_dict)。"""
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if token:
        h["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        return e.code, payload


def make_otp() -> str:
    """用后端真实密钥计算当前 6 位动态码。"""
    from app import auth
    return auth._totp_at(auth.get_secret(), int(time.time()))
