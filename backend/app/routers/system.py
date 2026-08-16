# -*- coding: utf-8 -*-
"""系统健康 / Windows 服务路由"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..modules import system_health, windows_services
from ..security import require_auth, require_role

router = APIRouter(prefix="/api/system", tags=["system"],
                   dependencies=[Depends(require_auth), Depends(require_role("admin"))])


@router.get("/health")
async def health():
    """本机系统健康（CPU/内存/磁盘/网络/进程）。"""
    return await asyncio.to_thread(system_health.get_health)


@router.get("/interfaces")
async def interfaces():
    """本机网卡状态与地址。"""
    return await asyncio.to_thread(system_health.get_interfaces)


@router.get("/services")
async def services():
    """Windows 服务列表。"""
    return await asyncio.to_thread(windows_services.list_services)


class ServiceAction(BaseModel):
    action: str  # start | stop


@router.post("/services/{name}/action")
async def service_action(name: str, body: ServiceAction):
    """启停服务（核心服务受保护）。"""
    ok, msg = await asyncio.to_thread(windows_services.service_action, name, body.action)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    await db.add_audit("admin", "service_action", name, body.action)
    return {"ok": True, "message": msg}


@router.get("/startup")
async def startup():
    """注册表/启动文件夹中的开机自启应用。"""
    return await asyncio.to_thread(windows_services.registry_startup_apps)
