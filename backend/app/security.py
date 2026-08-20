# -*- coding: utf-8 -*-
"""鉴权依赖：仅接受登录后的会话令牌（Redis 存储的 HMAC 签名 Bearer）

安全整改（P1-03）：
- 业务接口一律只认 Bearer 会话令牌，不再允许 `x-otp-token` 直通。
- TOTP 动态码仅用于 `/auth/login` 换取会话令牌（见 routers/auth.py），
  换到令牌后所有业务 API 都走 Bearer，使登录限速（仅保护 /auth/login）覆盖全链路。
- 登录失败限速只保护 /auth/login，因此业务接口不能再被 TOTP 绕过。

RBAC：require_role(*roles) 在鉴权通过后校验角色（默认 admin），保护高危路由。
"""
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth

_bearer = HTTPBearer(auto_error=False)


def _raise_unauth():
    raise HTTPException(status_code=401, detail="需要有效的登录会话令牌")


def _raise_forbidden():
    raise HTTPException(status_code=403, detail="当前角色无权执行该操作")


def _resolve_role(cred: HTTPAuthorizationCredentials | None) -> str:
    """解析请求身份，返回角色字符串；鉴权失败直接抛 401。

    仅接受 Bearer 会话令牌（HMAC 签名 + Redis 登记 + TTL）。
    """
    token = cred.credentials if (cred and cred.credentials) else None
    if not token:
        _raise_unauth()
    if auth.verify_token(token):
        return auth.get_token_role(token)
    _raise_unauth()
    return "admin"  # 不可达


def require_auth(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> bool:
    """任意已登录（Bearer 会话）即可。"""
    _resolve_role(cred)
    return True


def require_role(*allowed_roles: str):
    """角色护栏：鉴权通过后必须处于 allowed_roles 之一，否则 403。

    单用户场景下角色恒为 admin，仅建立权限骨架，不改变现有行为；
    未来接入多用户时，登录签发令牌即带角色，此处自动生效。
    """

    def _dep(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> str:
        role = _resolve_role(cred)
        if allowed_roles and role not in allowed_roles:
            _raise_forbidden()
        return role

    return _dep
