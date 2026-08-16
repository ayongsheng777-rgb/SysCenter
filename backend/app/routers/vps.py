# -*- coding: utf-8 -*-
"""VPS / 代理矩阵路由：实例管理 + 存活延迟刷新"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..modules import net_probe
from ..security import require_auth

router = APIRouter(prefix="/api/vps", tags=["vps"], dependencies=[Depends(require_auth)])


class VpsIn(BaseModel):
    id: int | None = None
    name: str
    host: str
    port: int = 22
    kind: str = "vps"      # vps | proxy
    note: str = ""
    enabled: bool = True


@router.get("")
async def list_vps():
    rows = await db.list_vps()
    # 附加实时存活（enabled 的才探测）
    out = []
    for r in rows:
        if r.get("enabled"):
            st = await asyncio.to_thread(net_probe.host_status, r["host"], r["port"])
        else:
            st = {"alive": False, "latency_ms": None, "port_open": None}
        r.update(st)
        out.append(r)
    return out


@router.post("")
async def upsert_vps(body: VpsIn):
    vid = await db.upsert_vps(body.model_dump())
    return {"ok": True, "id": vid}


@router.delete("/{vid}")
async def delete_vps(vid: int):
    ok = await db.delete_vps(vid)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该实例")
    return {"ok": True}


@router.post("/refresh")
async def refresh():
    """重新探测所有启用实例的存活与延迟。"""
    rows = await db.list_vps()
    out = []
    for r in rows:
        if r.get("enabled"):
            st = await asyncio.to_thread(net_probe.host_status, r["host"], r["port"])
        else:
            st = {"alive": False, "latency_ms": None, "port_open": None}
        r.update(st)
        out.append(r)
    return out
