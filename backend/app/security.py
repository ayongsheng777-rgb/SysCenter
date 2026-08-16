# -*- coding: utf-8 -*-
"""鉴权依赖：同时支持 TOTP 动态码 与 登录后的会话令牌（Redis 存储）

- 请求头 x-otp-token: 6 位动态码（与 Authenticator 对齐）
- 请求头 Authorization: Bearer <session_token>（登录接口签发，存于 Redis，带 TTL）
任一通过即可。登录后前端优先用 Bearer 令牌。

RBAC：require_role(*roles) 在鉴权通过后校验角色（默认 admin），保护高危路由。
"""
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth

_bearer = HTTPBearer(auto_error=False)


def _raise_unauth():
    raise HTTPException(status_code=401, detail="需要有效的 OTP 动态码或登录令牌")


def _raise_forbidden():
    raise HTTPException(status_code=403, detail="当前角色无权执行该操作")


def _resolve_role(
    x_otp_token: str | None,
    cred: HTTPAuthorizationCredentials | None,
) -> str:
    """解析请求身份，返回角色字符串；鉴权失败直接抛 401。"""
    token = cred.credentials if (cred and cred.credentials) else None
    if token:
        if auth.verify_token(token):
            return auth.get_token_role(token)
        _raise_unauth()  # 令牌形式存在但不合法 -> 拒绝，避免退回 TOTP 造成混淆
    if x_otp_token:
        if auth.verify_otp(x_otp_token):
            return "admin"  # TOTP 直登视为管理员
        _raise_unauth()
    _raise_unauth()
    return "admin"  # 不可达


def require_auth(
    x_otp_token: str | None = Header(None),
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> bool:
    """任意已登录（TOTP 或 Bearer）即可。"""
    _resolve_role(x_otp_token, cred)
    return True


def require_role(*allowed_roles: str):
    """角色护栏：鉴权通过后必须处于 allowed_roles 之一，否则 403。

    单用户场景下角色恒为 admin，仅建立权限骨架，不改变现有行为；
    未来接入多用户时，登录签发令牌即带角色，此处自动生效。
    """

    def _dep(
        x_otp_token: str | None = Header(None),
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> str:
        role = _resolve_role(x_otp_token, cred)
        if allowed_roles and role not in allowed_roles:
            _raise_forbidden()
        return role

    return _dep
