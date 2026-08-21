# -*- coding: utf-8 -*-
"""技能管理路由：列出技能 / 配置（skill_key、第三方密钥、触发词、开关）

- GET  /api/skills          列出全部技能（含被禁用的）
- PUT  /api/skills/{skill_id}  更新某技能配置（key 改名、触发词、密钥、开关）
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import skills_config
from ..security import require_auth, require_role
from .. import secret_vault

log = logging.getLogger("skills")

router = APIRouter(prefix="/api/skills", tags=["skills"],
                   dependencies=[Depends(require_auth), Depends(require_role("admin"))])

_MASK = "****"


def _registry():
    from ..skills import get_registry
    return get_registry()


@router.get("")
async def list_skills():
    """列出全部技能（刷新 registry 以登记新装技能，再合并配置返回）。"""
    reg = _registry()
    reg.reload()
    reg_skills = reg.get_available_skills()
    reg_by_id = {s["skill_id"]: s for s in reg_skills}

    out = []
    for sid, entry in skills_config.list_skills().items():
        has_key = bool((entry.get("api_key") or "").strip())
        desc = entry.get("description", "")
        reg_item = reg_by_id.get(sid)
        if reg_item:
            desc = reg_item.get("desc") or desc
        out.append({
            "skill_id": sid,
            "key": entry.get("key", ""),
            "name": entry.get("name", ""),
            "source": entry.get("source", ""),
            "enabled": entry.get("enabled", True),
            "has_api_key": has_key,
            "trigger_keywords": entry.get("trigger_keywords", []),
            "desc": desc,
        })
    return out


class SkillUpdate(BaseModel):
    key: str | None = None
    name: str | None = None
    enabled: bool | None = None
    api_key: str | None = None          # 明文；空串=清除；****开头=保留原值
    trigger_keywords: list | None = None


@router.put("/{skill_id:path}")
async def update_skill(skill_id: str, body: SkillUpdate):
    entry = skills_config.get_skill(skill_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="技能不存在")

    if body.key is not None:
        entry["key"] = (body.key or "").strip()
    if body.name is not None:
        entry["name"] = (body.name or "").strip()
    if body.enabled is not None:
        entry["enabled"] = bool(body.enabled)
    if body.trigger_keywords is not None:
        entry["trigger_keywords"] = [str(k).strip() for k in body.trigger_keywords if str(k).strip()]
    if body.api_key is not None:
        ak = (body.api_key or "").strip()
        if ak and not ak.startswith(_MASK):
            entry["api_key"] = secret_vault.encrypt_str(ak)
        elif ak == "":
            entry["api_key"] = ""

    if not entry.get("key"):
        raise HTTPException(status_code=400, detail="技能 key 不能为空")

    skills_config.upsert_skill(skill_id, entry)
    # 立即重载，让飞书/网页调用立刻生效
    _registry().reload()
    return {"ok": True, "skill_id": skill_id}
