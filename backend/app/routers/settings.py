# -*- coding: utf-8 -*-
"""运行时设置路由：模型配置 / 飞书 / 监控目标（落库 app_settings，免重启热更新）"""
import json
import logging

log = logging.getLogger("settings")

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, feishu
from ..config import (SECRET_KEYS, apply_overrides, mask_secret, runtime_dict,
                      settings)
from ..security import require_auth, require_role

router = APIRouter(prefix="/api/settings", tags=["settings"],
                   dependencies=[Depends(require_auth), Depends(require_role("admin"))])

_MASK = "****"


class SettingsIn(BaseModel):
    items: dict  # {key: value}


@router.get("")
async def get_settings():
    return {
        "runtime": runtime_dict(),
        "ai_ready": settings.ai_ready,
        "feishu_enabled": settings.feishu_enabled,
        "automation_enabled": settings.automation_enabled,
        "health_check_enabled": settings.health_check_enabled,
    }


@router.put("")
async def put_settings(body: SettingsIn):
    raw = {}
    for k, v in body.items.items():
        # 密钥类：若前端回传的是脱敏占位符（****xxxx），保留原值不覆盖
        if k in SECRET_KEYS and isinstance(v, str) and v.startswith(_MASK):
            existing = getattr(settings, k, "")
            if existing:
                raw[k] = existing
            continue
        # 列表/字典序列化存储
        if isinstance(v, (list, dict)):
            raw[k] = json.dumps(v, ensure_ascii=False)
        else:
            raw[k] = v
    # 写入库（注意：Secret 若被占位符吞掉，需保留原库值）
    for k, v in raw.items():
        if k in SECRET_KEYS and isinstance(v, str) and v.startswith(_MASK):
            continue
        await db.upsert_setting(k, str(v) if not isinstance(v, str) else v)
    apply_overrides(raw)
    await db.add_audit("admin", "settings_update", "", "更新运行时设置")
    # 飞书 bot 热启动：凭据补全且启用、但当前未运行时，保存后自动拉起（免重启）
    if settings.feishu_enabled and settings.feishu_app_id and settings.feishu_app_secret:
        svc = feishu.feishu_service
        if not svc._thread or not svc._thread.is_alive():
            try:
                feishu.start_feishu_bot()
            except Exception as e:  # noqa: BLE001
                log.warning("飞书 bot 热启动失败：%s", e)
    return {"ok": True, "runtime": runtime_dict()}


@router.get("/ai-usage")
async def ai_usage(days: int = 30):
    return await db.ai_usage_summary(days)
