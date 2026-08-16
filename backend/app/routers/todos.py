# -*- coding: utf-8 -*-
"""AI 智能待办与经验沉淀模块（需鉴权）

继承指南的设计，但落地到 SysCenter 既有架构：
- 持久化用现有 Postgres（todos 表，含 is_sys_scope/status/suggestion）
- AI 调用复用 ai_client（多模型兜底 + 用量落库），不裸 requests
- bot 指令与 REST 共用 db.todos
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import ai_client, db
from ..config import settings
from ..security import require_auth

log = logging.getLogger("todos")

router = APIRouter(prefix="/api/todos", tags=["todos"], dependencies=[Depends(require_auth)])


class TodoIn(BaseModel):
    content: str


class StatusIn(BaseModel):
    status: str  # 未完成 | 部分完成 | 已完成


# 范畴判定：是否属 Windows 运维 / 局域网 / NAS / 软路由 / VPS / Docker 自动化
_SCOPE_SYSTEM = (
    "你是运维分类器。判断下面这条待办是否属于 Windows 系统运维、局域网、"
    "NAS、软路由、VPS 或 Docker 自动化范畴。只回答「是」或「否」，不要解释。"
)


@router.get("")
async def list_todos(all: int = 0, query: str = ""):
    return await db.list_todos(only_open=not all, limit=100, query=(query or "").strip())


@router.post("")
async def add_todo(body: TodoIn):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")

    # 轻量级范畴判定（AI 未启用时默认计为日常杂项，不阻塞入库）
    is_sys = 0
    if settings.ai_enabled and settings.ai_ready:
        try:
            verdict = await ai_client.chat(_SCOPE_SYSTEM, content, max_tokens=8, temperature=0.0,
                                           cache_ttl=3600)
            if verdict and "是" in verdict:
                is_sys = 1
        except Exception as e:  # noqa: BLE001
            log.warning("待办范畴判定失败(忽略): %s", e)

    tid = await db.add_todo(content, is_sys_scope=is_sys, status="未完成")
    item = await db.get_todo(tid)
    return item


@router.put("/{tid}/status")
async def update_status(tid: int, body: StatusIn):
    ok = await db.update_todo_status(tid, body.status)
    if not ok:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"ok": True}


@router.delete("/{tid}")
async def remove_todo(tid: int):
    ok = await db.delete_todo(tid)
    if not ok:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"ok": True}


@router.post("/{tid}/suggest")
async def suggest(tid: int):
    task = await db.get_todo(tid)
    if not task:
        raise HTTPException(status_code=404, detail="待办不存在")
    if not settings.ai_enabled or not settings.ai_ready:
        raise HTTPException(status_code=400, detail="AI 未启用或未配置 Key（设置页开启）")

    prompt = (
        f"针对系统运维任务：【{task['content']}】，当前状态【{task['status']}】。"
        f"请给出可执行的排障思路或具体操作建议（中文，分步骤）。"
    )
    chain = settings.get_scenario_fallback_chain("diagnose")
    suggestion = await ai_client.chat_with_fallback(
        "你是资深 Windows 系统与网络运维工程师，回答要具体、可操作。", prompt, chain,
        max_tokens=1500, temperature=0.3)
    if not suggestion:
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{ai_client.stats_dict().get('last_error', '未知错误')}")
    await db.update_todo_suggestion(tid, suggestion)
    return {"suggestion": suggestion}


# ---------------- 全局经验提炼 ----------------
_EXP_SYSTEM = (
    "你是一个资深 IT 系统架构师。以下是本中心历史的系统运维、网络管理与自动化部署记录。"
    "请进行整体分析，提炼出【专属运维经验与避坑指南】。要求：\n"
    "1. 归纳出系统最常出现的脆弱点或高频故障模块。\n"
    "2. 总结出一套针对性的 SOP（标准作业程序）或优化建议，防止问题复发。"
)


@router.post("/experience/analyze")
async def analyze_experience():
    corpus = await db.experience_corpus(limit=50)
    if not corpus:
        return {"report": "系统记录不足，暂无法生成经验总结。请多积累一些「核心系统」范畴且已完成/有 AI 建议的排障记录。"}

    history_text = "\n\n".join(
        f"问题/任务：{c['content']}\n处理建议：{c.get('suggestion') or '（无）'}" for c in corpus)
    prompt = f"【历史记录存档（共 {len(corpus)} 条）】：\n{history_text}"

    chain = settings.get_scenario_fallback_chain("experience")
    report = await ai_client.chat_with_fallback(_EXP_SYSTEM, prompt, chain,
                                                max_tokens=2500, temperature=0.4)
    if not report:
        raise HTTPException(status_code=502, detail=f"AI 调用失败：{ai_client.stats_dict().get('last_error', '未知错误')}")
    return {"report": report, "count": len(corpus)}
