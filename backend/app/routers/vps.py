# -*- coding: utf-8 -*-
"""VPS / 代理矩阵路由：实例管理 + 存活延迟刷新（并发探测）"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..modules import net_probe
from ..security import require_auth

router = APIRouter(prefix="/api/vps", tags=["vps"], dependencies=[Depends(require_auth)])

# 并发上限：避免一次刷新打爆本机线程池（100 台 VPS 也不会卡死）
_PROBE_SEMAPHORE = asyncio.Semaphore(20)


class VpsIn(BaseModel):
    id: int | None = None
    name: str
    host: str
    port: int = 22
    kind: str = "vps"      # vps | proxy
    note: str = ""
    enabled: bool = True


async def _probe_one(r: dict) -> dict:
    r = dict(r)  # 不污染缓存行
    if r.get("enabled"):
        try:
            async with _PROBE_SEMAPHORE:
                st = await asyncio.to_thread(net_probe.host_status, r["host"], r["port"])
        except Exception:  # noqa: BLE001
            st = {"alive": False, "latency_ms": None, "port_open": None}
    else:
        st = {"alive": False, "latency_ms": None, "port_open": None}
    r.update(st)
    return r


@router.get("")
async def list_vps():
    rows = await db.list_vps()
    return await asyncio.gather(*[_probe_one(r) for r in rows])


@router.post("")
async def upsert_vps(body: VpsIn):
    vid = await db.upsert_vps(body.model_dump())
    await db.add_audit("admin", "vps_upsert", body.name, f"kind={body.kind}")
    return {"ok": True, "id": vid}


@router.delete("/{vid}")
async def delete_vps(vid: int):
    ok = await db.delete_vps(vid)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该实例")
    await db.add_audit("admin", "vps_delete", str(vid))
    return {"ok": True}


@router.post("/refresh")
async def refresh():
    """并发重新探测所有启用实例的存活与延迟。"""
    rows = await db.list_vps()
    return await asyncio.gather(*[_probe_one(r) for r in rows])
