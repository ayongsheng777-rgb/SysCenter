# -*- coding: utf-8 -*-
"""告警日志路由"""
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..security import require_auth, require_role

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(require_auth)])


@router.get("")
async def alerts(limit: int = Query(50, le=500)):
    return await db.recent_alerts(limit)


@router.post("/{aid}/ack", dependencies=[Depends(require_role("admin"))])
async def ack_alert(aid: int):
    """确认/标记已读告警（仅作状态标记，不删除记录）。"""
    ok = await db.acknowledge_alert(aid)
    if not ok:
        raise HTTPException(status_code=404, detail="告警不存在")
    await db.add_audit("admin", "alert_ack", str(aid))
    return {"ok": True}


@router.delete("/{aid}", dependencies=[Depends(require_role("admin"))])
async def remove_alert(aid: int):
    ok = await db.delete_alert(aid)
    if not ok:
        raise HTTPException(status_code=404, detail="告警不存在")
    await db.add_audit("admin", "alert_delete", str(aid))
    return {"ok": True}
