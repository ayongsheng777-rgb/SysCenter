# -*- coding: utf-8 -*-
"""飞书推送路由（手动触发告警/通知）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import feishu
from ..config import settings
from ..security import require_auth

router = APIRouter(prefix="/api/notify", tags=["notify"], dependencies=[Depends(require_auth)])


class AlertRequest(BaseModel):
    message: str
    level: str = "info"   # info | warning | critical


@router.post("/feishu")
async def push_feishu(req: AlertRequest):
    if not settings.feishu_enabled or not settings.feishu_webhook:
        raise HTTPException(status_code=400, detail="飞书未启用或未配置 webhook")
    ok, msg = await feishu.notify(req.level, "manual", req.message)
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"status": "success"}


@router.get("/feishu/status")
async def feishu_status():
    return {"enabled": settings.feishu_enabled, "configured": bool(settings.feishu_webhook)}


@router.post("/feishu/test")
async def feishu_test():
    """发送一条测试卡片，验证 webhook + 签名是否可用。"""
    if not settings.feishu_enabled or not settings.feishu_webhook:
        raise HTTPException(status_code=400, detail="飞书未启用或未配置 webhook")
    ok, msg = await feishu.send_card("✅ SysCenter 飞书连通测试",
                                     ["这是一条来自 SysCenter 的测试消息。", "若你看到它，说明 webhook 配置正确。"])
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"status": "success"}
