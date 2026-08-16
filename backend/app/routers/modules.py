# -*- coding: utf-8 -*-
"""模块说明路由（对应指南 modules/info 的不可操作说明）"""
from fastapi import APIRouter, Depends, HTTPException

from ..security import require_auth

router = APIRouter(prefix="/api/modules", tags=["modules"], dependencies=[Depends(require_auth)])

_INFO_MAP = {
    "docker": "【说明】容器管理已被隔离。如需管理容器节点（含夸克网盘等应用），请移步局域网内的 Portainer 或 aaPanel 面板。",
    "core_service": "【警告】此 Windows 核心服务禁止在 SysCenter 面板直接关闭，以免导致系统崩溃。",
    "nas": "【说明】Synology NAS 状态为只读探测（ping + DSM 端口），不做写操作。",
    "tv": "【说明】tv 盒子仅做在线状态监测。",
}


@router.get("/info")
async def module_info(module_name: str):
    return {"module": module_name, "instruction": _INFO_MAP.get(module_name, "暂无说明")}
