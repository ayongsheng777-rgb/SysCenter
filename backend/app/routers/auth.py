# -*- coding: utf-8 -*-
"""鉴权路由：OTP 绑定 / 登录 / 重置（换绑）

安全门：
- 获取绑定信息仅在未绑定时返回密钥/二维码。
- 重置（换绑）必须同时持有【有效会话令牌(admin)】+【当前 6 位动态码】。
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from .. import auth, db
from ..security import require_role

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 登录失败限速（内存态，重启清空；单管理员本机场景足够）
_LOGIN_FAILS = {}          # ip -> [fail_count, last_fail_ts]
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SEC = 300


class OtpIn(BaseModel):
    otp: str


class ResetOut(BaseModel):
    secret: str = ""
    otpauth_uri: str = ""
    qr: str = ""
    reset: bool = False


@router.get("/setup")
def setup():
    """获取 OTP 绑定信息（仅在尚未绑定时返回密钥/二维码 URI）。"""
    if not auth.is_setup_open():
        return {"setup_open": False, "otpauth_uri": "", "secret": "", "qr": "",
                "hint": "已完成绑定或使用了环境变量密钥，密钥不再暴露"}
    uri = auth.otpauth_uri()
    from ..qrutil import qr_data_url
    return {"setup_open": True, "otpauth_uri": uri, "secret": auth.get_secret(),
            "qr": qr_data_url(uri), "issuer": auth.OTP_ISSUER}


@router.post("/login")
async def login(body: OtpIn, request: Request):
    """用 6 位动态码换取会话令牌。首次成功会标记已绑定。含简单失败限速。"""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    rec = _LOGIN_FAILS.get(ip)
    if rec and rec[0] >= _LOGIN_MAX_FAILS and now - rec[1] < _LOGIN_LOCK_SEC:
        wait = int(_LOGIN_LOCK_SEC - (now - rec[1]))
        raise HTTPException(status_code=429, detail=f"登录失败过多，请 {wait} 秒后再试")
    # 输入校验：OTP 必须是 6 位数字；格式非法直接 400，且不计入限速失败（避免被恶意锁管理员）
    if not (body.otp and isinstance(body.otp, str) and body.otp.isdigit() and len(body.otp) == 6):
        raise HTTPException(status_code=400, detail="OTP 必须为 6 位数字")
    if not auth.verify_otp(body.otp):
        f = _LOGIN_FAILS.setdefault(ip, [0, now])
        f[0] += 1
        f[1] = now
        raise HTTPException(status_code=403, detail="OTP 验证失败")
    _LOGIN_FAILS.pop(ip, None)
    auth.mark_enrolled()
    res = auth.generate_token("admin")
    # 审计日志为尽力而为：即使 DB 瞬时不可用也不应阻断登录（避免冷启动竞态把刚通过验证的用户弹回）
    try:
        await db.add_audit("admin", "login", ip, "OK")
    except Exception:  # noqa: BLE001
        pass
    return res


@router.post("/reset")
async def reset(body: OtpIn, _auth: str = Depends(require_role("admin"))) -> ResetOut:
    """换绑验证器：需 admin 登录态 + 当前 6 位动态码。返回新密钥+二维码，旧令牌立即失效。"""
    if not auth.verify_otp(body.otp):
        raise HTTPException(status_code=403, detail="当前动态码校验失败")
    res = auth.reset_otp()
    if res is None:
        raise HTTPException(status_code=400, detail="环境变量 OTP_SECRET 模式下不支持重置")
    await db.add_audit("admin", "reset_otp", "", "更换验证器")
    return ResetOut(secret=res["secret"], otpauth_uri=res["otpauth_uri"],
                   qr=res.get("qr", ""), reset=True)


@router.post("/logout")
async def logout(authorization: str | None = Header(None)):
    """吊销服务端会话令牌（从 Redis/内存移除），前端随后清除本地令牌。"""
    if authorization and authorization.lower().startswith("bearer "):
        auth.revoke_token(authorization[7:].strip())
    await db.add_audit("admin", "logout", "", "")
    return {"ok": True}
