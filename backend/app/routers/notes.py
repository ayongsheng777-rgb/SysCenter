# -*- coding: utf-8 -*-
"""AI 笔记 / 知识库模块（需鉴权）

- 持久化用现有 Postgres（ai_notes 表）
- 录入 API Key 类时，保存前按服务商真发最小请求探活（deepseek/siliconflow/openai），记录验证结果
- 「问 AI」：关键词匹配笔记 → 命中内容喂给大模型提炼答案（复用 ai_client，无新增依赖）
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import ai_client, db
from ..config import settings
from ..security import require_auth, require_role
from .. import sensitive

log = logging.getLogger("notes")

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_auth)])

# 已知 LLM 服务商 base_url（用于 API Key 探活）
_PROVIDER_BASE = {
    "deepseek": "https://api.deepseek.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openai": "https://api.openai.com/v1",
}

_VALID_CATEGORIES = ("apikey", "code", "tech", "other")


class NoteIn(BaseModel):
    title: str
    category: str = "other"      # apikey | tech | other
    provider: str = ""           # 仅 apikey：deepseek|siliconflow|openai|other
    content: str
    tags: list[str] = []


class NotePatch(BaseModel):
    title: str | None = None
    category: str | None = None
    provider: str | None = None
    content: str | None = None
    tags: list[str] | None = None


class AskIn(BaseModel):
    question: str
    limit: int = 8


async def _test_api_key(provider: str, key: str) -> tuple[str, str]:
    """返回 (tested, test_result)。tested ∈ ok|fail|skipped。"""
    base = _PROVIDER_BASE.get(provider)
    if not base or not key:
        return "skipped", "未知服务商或未填 Key，跳过自动验证"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code == 200:
            return "ok", "验证通过：Key 有效，可列出模型"
        if r.status_code == 401:
            return "fail", "验证失败：Key 无效或已失效（401）"
        if r.status_code == 403:
            return "fail", "验证失败：该 Key 无权限（403）"
        return "fail", f"验证失败：HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return "fail", f"验证异常：{type(e).__name__}（网络不通或需代理）"


# 公共别名，供飞书 bot 等其它入口复用
PROVIDER_BASE = _PROVIDER_BASE
_PROVIDER_CN = {"siliconflow": "硅基流动", "deepseek": "DeepSeek", "openai": "OpenAI", "other": "其他"}


def _note_tags(provider: str) -> list[str]:
    """给 apikey 笔记生成标签：英文服务商 + 中文别名，便于中英文都能检索到。"""
    tags = ["API", "Key"]
    if provider:
        tags.append(provider)
        cn = _PROVIDER_CN.get(provider)
        if cn:
            tags.append(cn)
    return tags


async def detect_provider(key: str) -> str:
    """按已知服务商依次 GET /models 探测 key 归属，无法确定返回 other。"""
    for provider, base in _PROVIDER_BASE.items():
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                return provider
        except Exception:  # noqa: BLE001
            continue
    return "other"


async def save_api_key_note(key: str, provider: str = "", title: str = "API Key") -> dict | None:
    """保存一条 apikey 笔记：探活通过才采用 provider；否则回退自动探测（纠正 AI 猜错服务商）。"""
    key = (key or "").strip()
    if not key:
        return None
    provider = (provider or "").strip()
    # 显式 provider 且探活通过 → 直接采用
    if provider in _PROVIDER_BASE:
        tested, test_result = await _test_api_key(provider, key)
        if tested == "ok":
            nid = await db.add_note(title, "apikey", provider, key, _note_tags(provider),
                                    tested=tested, test_result=test_result)
            return await db.get_note(nid)
    # 否则自动探测服务商（能准确识别，纠正 openai 等误判）
    provider = await detect_provider(key)
    tested, test_result = await _test_api_key(provider, key)
    nid = await db.add_note(title, "apikey", provider, key, _note_tags(provider),
                            tested=tested, test_result=test_result)
    return await db.get_note(nid)


@router.get("")
async def list_notes(q: str = "", category: str = "", limit: int = 100):
    return await db.list_notes(q=q, category=category, limit=limit)


@router.post("", dependencies=[Depends(require_role("admin"))])
async def create_note(body: NoteIn):
    title = (body.title or "").strip()
    content = (body.content or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title 与 content 不能为空")
    category = body.category if body.category in _VALID_CATEGORIES else "other"

    # code（一次性验证码/授权码）不是模型密钥，不拿去探活，避免误报“未验证”
    provider = body.provider if category == "apikey" else ""
    tested, test_result = "untested", ""
    if category == "apikey":
        tested, test_result = await _test_api_key(provider, content)
    elif category == "code":
        tested, test_result = "skipped", "一次性验证码，无需验证可用性"

    tags = list(body.tags)
    if category == "code" and not tags:
        tags = ["验证码"]

    nid = await db.add_note(title, category, provider, content,
                            tags, tested=tested, test_result=test_result)
    note = await db.get_note(nid)
    await db.add_audit("admin", "note_create", category, f"title={title} tested={tested}")
    return note


@router.get("/{nid}")
async def get_note(nid: int):
    note = await db.get_note(nid)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


@router.put("/{nid}", dependencies=[Depends(require_role("admin"))])
async def update_note(nid: int, body: NotePatch):
    existing = await db.get_note(nid)
    if not existing:
        raise HTTPException(status_code=404, detail="笔记不存在")
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    # 若改了 apikey 内容或服务商，重新探活
    if existing["category"] == "apikey" and ("content" in fields or "provider" in fields):
        provider = fields.get("provider", existing["provider"])
        key = fields.get("content", existing["content"])
        tested, test_result = await _test_api_key(provider, key)
        fields["tested"] = tested
        fields["test_result"] = test_result
    ok = await db.update_note(nid, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return await db.get_note(nid)


@router.delete("/{nid}", dependencies=[Depends(require_role("admin"))])
async def remove_note(nid: int):
    ok = await db.delete_note(nid)
    if not ok:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return {"ok": True}


@router.post("/ask")
async def ask(body: AskIn):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not settings.ai_enabled or not settings.ai_ready:
        raise HTTPException(status_code=400, detail="AI 未启用或未配置 Key（设置页开启）")

    notes = await db.list_notes(q=q, limit=body.limit)
    if not notes:
        return {"found": False,
                "answer": "没有找到相关笔记。可以换个说法，或先去「笔记/知识库」添加这条信息。",
                "sources": []}

    corpus = "\n\n".join(
        f"【笔记 {n['id']} | {n['title']} | {n['category']}】\n{n['content']}"
        + (f"\n可用性验证：{n.get('tested')} — {n.get('test_result')}"
           if n.get("test_result") else "")
        for n in notes)
    system = (
        "你是阿勇的笔记助手。下面提供了若干条【历史笔记】。"
        "请只根据这些内容回答用户的问题，从中提炼出最直接相关的信息。"
        "严禁编造笔记里没有的内容；如果笔记不足以回答，明确说「笔记里没有相关信息」。"
        "回答用中文，简洁、可直接取用。"
    )
    # P2-08：笔记可能含 API Key，发 AI 前脱敏
    safe_corpus = sensitive.redact(corpus)
    user = f"用户问题：{q}\n\n=== 相关笔记 ===\n{safe_corpus}"
    chain = settings.get_scenario_fallback_chain("notes")
    answer = await ai_client.chat_with_fallback(system, user, chain, max_tokens=1200, temperature=0.2)
    if not answer:
        raise HTTPException(status_code=502,
                            detail=f"AI 调用失败：{ai_client.stats_dict().get('last_error', '未知错误')}")
    return {"found": True, "answer": answer,
            "sources": [{"id": n["id"], "title": n["title"], "category": n["category"]} for n in notes]}
