# -*- coding: utf-8 -*-
"""网络与资产监控路由：网卡、局域网扫描、NAS、tv 盒子"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..modules import system_health, net_probe
from ..config import settings
from ..security import require_auth, require_role

router = APIRouter(prefix="/api/network", tags=["network"], dependencies=[Depends(require_auth)])


@router.get("/interfaces")
async def interfaces():
    return await asyncio.to_thread(system_health.get_interfaces)


class LanScanIn(BaseModel):
    subnet: str = ""       # 形如 192.168.1（不含末尾点）；留空用设置里的 lan_subnet
    timeout_ms: int = 800


@router.post("/lan-scan", dependencies=[Depends(require_role("admin"))])
async def lan_scan(body: LanScanIn):
    """扫描局域网在线设备。"""
    subnet = body.subnet or settings.lan_subnet
    if not subnet:
        raise HTTPException(status_code=400, detail="未提供网段，请在设置中配置 LAN_SUBNET")
    hosts = await asyncio.to_thread(net_probe.scan_subnet, subnet, body.timeout_ms)
    await db.add_audit("admin", "lan_scan", subnet, f"count={len(hosts)}")
    return {"subnet": subnet, "count": len(hosts), "hosts": hosts}


@router.get("/nas")
async def nas():
    """Synology NAS 状态（ping + DSM 端口）。"""
    host = settings.nas_host
    if not host:
        return {"configured": False, "host": "", "alive": False}
    st = await asyncio.to_thread(net_probe.host_status, host, settings.nas_port)
    st["configured"] = True
    st["kind"] = "synology-nas"
    return st


@router.get("/tv")
async def tv():
    """tv 盒子在线状态（ping）。"""
    host = settings.tv_host
    if not host:
        return {"configured": False, "host": "", "alive": False}
    st = await asyncio.to_thread(net_probe.host_status, host)
    st["configured"] = True
    st["kind"] = "tv-box"
    return st
