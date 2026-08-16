# -*- coding: utf-8 -*-
"""操作审计日志查看接口（仅管理员）"""
from fastapi import APIRouter, Depends, Query

from .. import db
from ..security import require_role

router = APIRouter(prefix="/api/audit", tags=["audit"],
                   dependencies=[Depends(require_role("admin"))])


@router.get("")
async def list_audit(limit: int = Query(200, le=1000)):
    """近期操作审计记录（登录/登出/改设置/启停服务等）。"""
    return await db.recent_audits(limit)
