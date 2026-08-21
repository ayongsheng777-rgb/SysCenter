# -*- coding: utf-8 -*-
"""自动灾变备份 API（需鉴权）：状态查询 + 手动触发"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import backup
from ..security import require_auth, require_role

log = logging.getLogger("backup")

router = APIRouter(prefix="/api/backup", tags=["backup"], dependencies=[Depends(require_auth)])


class RunIn(BaseModel):
    type: str  # full | incr


@router.get("/status")
async def status():
    return await backup.backup_status()


@router.post("/run", dependencies=[Depends(require_role("admin"))])
async def run(body: RunIn):
    try:
        return await backup.run_backup(body.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
