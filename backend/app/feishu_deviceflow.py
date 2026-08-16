# -*- coding: utf-8 -*-
"""飞书扫码自动配置 —— 设备授权流（Device Authorization Grant, RFC 8628）

移植自 dragons-breath/backend/app/feishu_deviceflow.py（同源 GoofishMasterDesktop）。
仅依赖 httpx，无需额外库。

核心思想（与旧的"手填 App ID/Secret"互补，作为主推方式）：
  * 二维码**不指向本站**，而是指向飞书官方授权地址 accounts.feishu.cn。
    用户用飞书 App 扫码后，打开的是飞书原生授权页（不经过本站、不丢哈希、
    不依赖本站公网可达性），确认授权即完成。
  * 授权完成后飞书**自动创建一个 PersonalAgent 自建应用**，并通过 poll 接口
    回传 app_id / app_secret / open_id —— 用户**无需手动去开放平台建应用、
    无需手填 App ID/Secret**，一并解决"缺凭据"与"扫码跳错页"两个痛点。

流程：
  1. POST /oauth/v1/app/registration  action=init   → 确认支持 client_secret
  2. POST 同上                        action=begin  → 拿 device_code + verification_uri_complete
  3. 前端用 verification_uri_complete 渲染二维码，用户扫码授权
  4. POST 同上                        action=poll   → 轮询直到拿到 client_id/client_secret
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict

import httpx

log = logging.getLogger("feishu.deviceflow")

_FEISHU_ACCOUNTS_DOMAIN = "https://accounts.feishu.cn"
_LARK_ACCOUNTS_DOMAIN = "https://accounts.larksuite.com"
_REGISTER_ENDPOINT = "/oauth/v1/app/registration"
_SOURCE = "syscenter"             # 渠道标识，飞书侧统计用
_ARCHETYPE = "PersonalAgent"     # 个人智能体应用模板


@dataclass
class QRCodeResult:
    scan_url: str          # 飞书官方授权地址，直接渲染成二维码
    poll_token: str        # = device_code，轮询用
    expires_in: int = 300


@dataclass
class PollResult:
    status: str                       # waiting / success / expired / fail
    credentials: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


class FeishuDeviceFlow:
    def __init__(self, domain: str = "feishu") -> None:
        self.domain = domain if domain in ("feishu", "lark") else "feishu"

    @property
    def endpoint(self) -> str:
        base = _LARK_ACCOUNTS_DOMAIN if self.domain == "lark" else _FEISHU_ACCOUNTS_DOMAIN
        return base + _REGISTER_ENDPOINT

    async def fetch_qrcode(self) -> QRCodeResult:
        async with httpx.AsyncClient(timeout=15) as client:
            init = await client.post(self.endpoint, data={"action": "init"})
            init.raise_for_status()
            methods = init.json().get("supported_auth_methods", [])
            if "client_secret" not in methods:
                raise RuntimeError(f"飞书不支持 client_secret 认证: {methods}")

            begin = await client.post(self.endpoint, data={
                "action": "begin",
                "archetype": _ARCHETYPE,
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            })
            begin.raise_for_status()
            data = begin.json()
            device_code = data.get("device_code", "")
            verification_uri = data.get("verification_uri_complete", "")
            expires_in = int(data.get("expires_in", 300) or 300)
            if not device_code or not verification_uri:
                raise RuntimeError(f"飞书返回缺少 device_code 或二维码 URL: {data}")
            scan_url = (f"{verification_uri}&source={_SOURCE}"
                        if "?" in verification_uri
                        else f"{verification_uri}?source={_SOURCE}")
            return QRCodeResult(scan_url=scan_url, poll_token=device_code,
                                expires_in=expires_in)

    async def poll_status(self, token: str) -> PollResult:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.endpoint,
                                     data={"action": "poll", "device_code": token})
            data = resp.json()

        if data.get("client_id") and data.get("client_secret"):
            user_info = data.get("user_info", {})
            return PollResult(status="success", credentials={
                "app_id": data["client_id"],
                "app_secret": data["client_secret"],
                "open_id": user_info.get("open_id", ""),
                "tenant_brand": user_info.get("tenant_brand", self.domain),
            })

        error = data.get("error", "")
        if error in ("expired_token", "invalid_grant"):
            return PollResult(status="expired", credentials={}, message="二维码已过期，请重新生成")
        if error == "access_denied":
            return PollResult(status="fail", credentials={}, message="用户拒绝了授权")
        if error and error not in ("authorization_pending", "slow_down"):
            return PollResult(status="fail", credentials={}, message=error)
        return PollResult(status="waiting", credentials={})
