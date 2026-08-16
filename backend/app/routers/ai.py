# -*- coding: utf-8 -*-
"""AI 诊断路由：把日志/异常交给 AI 诊断大脑（DeepSeek 等，带模型兜底）"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import ai_client, db
from ..config import settings
from ..security import require_auth, require_role

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(require_auth)])


class LogRequest(BaseModel):
    log_content: str
    scenario: str = "diagnose"


_SYSTEM = (
    "你是一名资深 Windows 系统与网络运维工程师，擅长根据系统日志、报错信息给出"
    "分步排障指导。请用中文回答，结构清晰：先给「可能原因」，再给「排查步骤」（命令或操作），"
    "最后给「修复建议」。若信息不足，明确指出还需补充什么。"
)


@router.post("/diagnose", dependencies=[Depends(require_role("admin"))])
async def diagnose(req: LogRequest):
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 未启用，请在设置中开启并填写 API Key")
    if not settings.ai_ready:
        raise HTTPException(status_code=400, detail="AI 模型未就绪（Key 为空或占位符）")
    chain = settings.get_scenario_fallback_chain(req.scenario)
    result = await ai_client.chat_with_fallback(_SYSTEM, req.log_content, chain,
                                                 max_tokens=1500, temperature=0.3)
    if not result:
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{ai_client.stats_dict().get('last_error', '未知错误')}")
    model = chain[0].get("model") if chain else settings.ai_model
    # 存档诊断历史（前端可回看 + 一键存为待办）
    try:
        await db.add_diagnose(req.log_content, result, model)
    except Exception as e:  # noqa: BLE001
        log.warning("诊断历史写入失败(忽略): %s", e)
    await db.add_audit("admin", "ai_diagnose", model, f"scenario={req.scenario}")
    return {"result": result, "model": model}


@router.get("/history")
async def diagnose_history(limit: int = Query(50, le=200)):
    """近期 AI 诊断历史（用于回看 + 存为待办）。"""
    return await db.list_diagnoses(limit)
