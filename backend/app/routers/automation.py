# -*- coding: utf-8 -*-
"""自动化剧本中枢路由：触发 n8n webhook 工作流"""
import json

import httpx

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..config import settings
from ..security import require_auth

router = APIRouter(prefix="/api/automation", tags=["automation"], dependencies=[Depends(require_auth)])


class TriggerIn(BaseModel):
    workflow: str = ""     # n8n webhook 路径或完整 URL（与 preset_id 二选一）
    payload: dict = {}
    preset_id: int | None = None   # 指定已保存的剧本预设时优先用 preset


class PresetIn(BaseModel):
    name: str
    workflow: str
    payload: dict = {}


@router.post("/presets")
async def save_preset(body: PresetIn):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name 不能为空")
    if not body.workflow or not body.workflow.strip():
        raise HTTPException(status_code=400, detail="workflow 不能为空")
    pid = await db.add_preset(body.name.strip(), body.workflow.strip(),
                              json.dumps(body.payload or {}, ensure_ascii=False))
    return {"ok": True, "id": pid}


@router.get("/presets")
async def list_presets():
    return await db.list_presets()


@router.delete("/presets/{pid}")
async def remove_preset(pid: int):
    ok = await db.delete_preset(pid)
    if not ok:
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"ok": True}


@router.post("/trigger")
async def trigger(body: TriggerIn):
    if not settings.automation_enabled:
        raise HTTPException(status_code=400, detail="自动化未启用，请在设置中开启")

    # 优先使用预设
    if body.preset_id:
        preset = await db.get_preset(body.preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail="预设不存在")
        try:
            payload = json.loads(preset["payload_json"]) if preset.get("payload_json") else {}
        except Exception:
            payload = {}
        workflow = preset["workflow"]
        label = preset["name"]
    else:
        if not body.workflow:
            raise HTTPException(status_code=400, detail="workflow 与 preset_id 至少提供一个")
        payload = body.payload or {}
        workflow = body.workflow
        label = workflow

    base = settings.n8n_webhook_base.rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="未配置 N8N_WEBHOOK_BASE")
    url = workflow if workflow.startswith("http") else f"{base}/{workflow.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=20.0, proxy=settings.ai_proxy or None) as cli:
            r = await cli.post(url, json=payload)
            ok = r.status_code < 300
            await db.save_alert("info", "automation",
                                f"触发 n8n 工作流 {label} -> HTTP {r.status_code}",
                                {"url": url, "status": r.status_code})
            return {"ok": ok, "status": r.status_code, "body": (r.text[:500] if r.content else "")}
    except Exception as e:
        await db.save_alert("warning", "automation",
                            f"触发 n8n 工作流失败: {type(e).__name__} {e}", {"url": url})
        raise HTTPException(status_code=502, detail=f"触发失败: {type(e).__name__} {e}")


@router.get("/status")
async def status():
    return {"enabled": settings.automation_enabled, "n8n_webhook_base": settings.n8n_webhook_base}
