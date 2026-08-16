# -*- coding: utf-8 -*-
"""鉴权依赖：同时支持 TOTP 动态码 与 登录后的会话令牌

- 请求头 x-otp-token: 6 位动态码（与 Authenticator 对齐，指南原方案）
- 请求头 Authorization: Bearer <session_token>（登录接口签发，dragons-breath 方案）
任一通过即可。登录后前端优先用 Bearer 令牌。
"""
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth

_bearer = HTTPBearer(auto_error=False)


def _raise():
    raise HTTPException(status_code=401, detail="需要有效的 OTP 动态码或登录令牌")


def require_auth(
    x_otp_token: str | None = Header(None),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> bool:
    # 1) 会话令牌（Bearer）
    if cred and cred.credentials:
        if auth.verify_token(cred.credentials):
            return True
        # 令牌形式存在但不合法 -> 直接拒绝（不退回 TOTP，避免混淆）
        _raise()
    # 2) TOTP 动态码
    if x_otp_token:
        if auth.verify_otp(x_otp_token):
            return True
        _raise()
    _raise()
    return False
