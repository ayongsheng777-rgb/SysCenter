# -*- coding: utf-8 -*-
"""飞书 bot 管理接口（需鉴权）：状态查看 / 手动重启 / 扫码自动配置"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, feishu
from ..config import apply_overrides, settings
from ..feishu_deviceflow import FeishuDeviceFlow
from ..qrutil import qr_data_url
from ..security import require_auth

log = logging.getLogger("feishu.bot")
router = APIRouter(prefix="/api/feishu/bot", tags=["feishu-bot"], dependencies=[Depends(require_auth)])


@router.get("/status")
async def bot_status():
    return feishu.feishu_service.status()


@router.post("/restart")
async def bot_restart():
    if not settings.feishu_enabled:
        return {"ok": False, "msg": "飞书未启用"}
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    await feishu.feishu_service.restart(loop)
    return {"ok": True, "status": feishu.feishu_service.status()}


# ==================== 扫码自动配置（设备授权流 RFC 8628） ====================
@router.post("/qrcode")
async def feishu_device_qrcode(domain: str = "feishu"):
    """生成飞书官方授权二维码（scan_url 由前端渲染，不经本站）。需登录态。"""
    try:
        res = await FeishuDeviceFlow(domain).fetch_qrcode()
    except Exception as e:  # noqa: BLE001
        log.exception("获取飞书授权二维码失败")
        raise HTTPException(502, f"获取二维码失败：{e}")
    return {"scan_url": res.scan_url, "qr": qr_data_url(res.scan_url),
            "poll_token": res.poll_token, "expires_in": res.expires_in}


@router.get("/qrcode/status")
async def feishu_device_qrcode_status(token: str = Query(...)):
    """轮询扫码授权结果；成功后写入凭据并热启动 Bot。需登录态。"""
    if not token:
        raise HTTPException(400, "缺少 token")
    try:
        poll = await FeishuDeviceFlow().poll_status(token)
    except Exception as e:  # noqa: BLE001
        log.exception("轮询飞书授权状态失败")
        raise HTTPException(502, f"轮询失败：{e}")

    if poll.status == "success":
        creds = poll.credentials
        changed = {
            "feishu_app_id": creds.get("app_id", ""),
            "feishu_app_secret": creds.get("app_secret", ""),
            "feishu_enabled": True,
        }
        for k, v in changed.items():
            await db.upsert_setting(k, json.dumps(v, ensure_ascii=False))
        apply_overrides(changed)
        log.info("飞书扫码配置成功 (app_id=%s…)，启动 Bot", changed["feishu_app_id"][:10])
        try:
            feishu.start_feishu_bot()
        except Exception:  # noqa: BLE001
            log.exception("扫码成功后启动 Bot 失败")
        return {"status": "success", "app_id": changed["feishu_app_id"],
                "open_id": creds.get("open_id", ""),
                "feishu_status": feishu.feishu_service.status()}
    return {"status": poll.status, "message": poll.message}
