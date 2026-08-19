# -*- coding: utf-8 -*-
"""AI 诊断客户端：复用本机 dragons-breath 的 chat / chat_with_fallback 方案

- 多模型池 + 场景轮循兜底
- 推理模型（reasoning）强制放宽 token/超时
- 支持中转站代理与 User-Agent 伪装
- 每次调用落库 ai_usage_log（与计费面板同构）
"""
import asyncio
import json
import logging
import threading
import time
from typing import Any, Optional

import httpx

from . import db
from .config import settings

log = logging.getLogger("ai")

# 占位符密钥（视为未配置）
_PLACEHOLDERS = ("your", "xxx", "sk-xxx", "changeme", "placeholder", "todo")

# 强制 temperature 的模型（大小写不敏感）
_FORCED_TEMP = {"kimi-k3": 1.0}
# 推理模型（答案可能在 reasoning_content，需放宽预算）。大小写不敏感子串匹配，
# 以兼容硅基流动等带路径前缀的模型名（如 deepseek-ai/DeepSeek-R1）。
_REASONING_SUBSTRINGS = ("deepseek-reasoner", "deepseek-r1", "deepseek-v4-pro", "kimi-k3", "o1", "o3", "qwq")
_MIN_REASONING_TOKENS = 2000
# 慢模型（仅放宽超时）
_SLOW_SUBSTRINGS = ("deepseek-r1", "deepseek-v4-pro", "qwen3.7-max", "qwen3-max", "qwen3-32b", "qwen3-235b")
_SLOW_TIMEOUT = 150.0

_sem = asyncio.Semaphore(4)          # 并发上限，避免压垮小水管
_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
stats = {"calls": 0, "ok": 0, "fail": 0, "cached": 0, "last_error": ""}


def _provider_of(profile: Optional[dict]) -> str:
    bu = (profile or {}).get("base_url") or ""
    if not bu:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(bu).hostname or ""
    except Exception:
        return ""
    for key in ("agentrouter", "deepseek", "dashscope", "aliyun", "qwen",
                "openai", "moonshot", "kimi", "zhipu", "glm", "anthropic", "claude", "siliconflow"):
        if key in host:
            return key
    return host


def _key(system: str, user: str, model: str) -> str:
    return f"{model}:{hash((system, user))}"


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def _extract_json(text: str) -> Optional[dict]:
    """尽力从模型输出中解析 JSON 对象。"""
    if not text:
        return None
    s = text.strip()
    # 去 ```json ``` 围栏
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        cand = s[start:end + 1]
        try:
            return json.loads(cand)
        except Exception:
            return None
    return None


def _log_ai_usage(model: str, profile: Optional[dict], usage: Optional[dict], latency_ms: int = 0):
    """落库 AI 用量（在异步上下文中 fire-and-forget，避免阻塞调用链）。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(db.log_ai_usage(
                model, (profile or {}).get("scenario", ""), _provider_of(profile),
                int((usage or {}).get("prompt_tokens") or 0),
                int((usage or {}).get("completion_tokens") or 0),
                usage is not None, latency_ms))
    except Exception:
        pass


async def chat(system: str, user: str, *,
               model_profile: Optional[dict] = None,
               max_tokens: int = 1200,
               temperature: float = 0.2,
               cache_ttl: int = 900,
               timeout: float = 45.0,
               json_mode: bool = False) -> Optional[str]:
    """返回模型文本输出；不可用或失败返回 None。"""
    if not settings.ai_enabled:
        return None
    prof = model_profile or settings.active_ai_profile()
    api_key = (prof.get("api_key") or "").strip()
    if not api_key or any(p in api_key.lower() for p in _PLACEHOLDERS):
        return None

    model = prof.get("model") or settings.ai_model
    ml = model.lower()
    ck = _key(system, user, model)
    with _cache_lock:
        hit = _cache.get(ck)
    if hit and time.time() - hit[0] < cache_ttl:
        stats["cached"] += 1
        return hit[1]

    temp = temperature
    for prefix, forced in _FORCED_TEMP.items():
        if prefix.lower() in ml:
            temp = forced
            break
    if any(s in ml for s in _REASONING_SUBSTRINGS):
        max_tokens = max(max_tokens, 2000)
        timeout = max(timeout, 150.0)
    if any(s in ml for s in _SLOW_SUBSTRINGS):
        timeout = max(timeout, _SLOW_TIMEOUT)

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temp,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode and any(s in ml for s in _REASONING_SUBSTRINGS):
        payload["response_format"] = {"type": "json_object"}

    url = (prof.get("base_url") or settings.ai_base_url).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    ua = (prof.get("user_agent") or settings.ai_user_agent or "").strip()
    if ua:
        headers["User-Agent"] = ua
    proxy = prof.get("proxy") or settings.ai_proxy or None

    async with _sem:
        stats["calls"] += 1
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as cli:
                r = await cli.post(url, headers=headers, json=payload)
                if r.status_code == 400 and "response_format" in payload:
                    payload.pop("response_format")
                    r = await cli.post(url, headers=headers, json=payload)
                if r.status_code != 200:
                    stats["fail"] += 1
                    _log_ai_usage(model, prof, None)
                    if r.status_code == 401:
                        stats["last_error"] = "API Key 无效或已失效（401）"
                    elif r.status_code == 403:
                        stats["last_error"] = "该 Key 无此模型调用权限（403）"
                    elif r.status_code == 404:
                        stats["last_error"] = "模型名不存在（404），请核对 Base URL 与模型名"
                    elif r.status_code == 429:
                        stats["last_error"] = "触发频率限制/额度不足（429）"
                    else:
                        stats["last_error"] = f"HTTP {r.status_code}: {r.text[:160]}"
                    log.warning("AI 返回 %s: %s", r.status_code, r.text[:200])
                    return None
                data = r.json()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            stats["fail"] += 1
            _log_ai_usage(model, prof, None)
            stats["last_error"] = "网络不通：无法连接 API 端点（境外模型需配代理）"
            return None
        except httpx.ReadTimeout:
            stats["fail"] += 1
            _log_ai_usage(model, prof, None)
            stats["last_error"] = "连接超时：模型响应过慢或代理不稳定"
            return None
        except Exception as e:
            stats["fail"] += 1
            _log_ai_usage(model, prof, None)
            stats["last_error"] = f"网络异常: {type(e).__name__}"
            return None

    try:
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        if not content:
            content = (msg.get("reasoning_content") or "").strip()
    except Exception:
        stats["fail"] += 1
        _log_ai_usage(model, prof, None)
        stats["last_error"] = "响应结构异常"
        return None

    usage = data.get("usage") or {}
    stats["ok"] += 1
    _log_ai_usage(model, prof, usage, int((time.monotonic() - t0) * 1000))
    with _cache_lock:
        _cache[ck] = (time.time(), content)
    return content


async def chat_with_fallback(system: str, user: str, chain: list[dict], **kw) -> Optional[str]:
    """按链顺序尝试模型，任一成功即返回；全部失败返回 None。"""
    if not chain:
        return None
    for i, prof in enumerate(chain):
        model_name = prof.get("model", "?")
        is_last = i == len(chain) - 1
        try:
            result = await chat(system, user, model_profile=prof, **kw)
            if result is not None:
                if i > 0:
                    log.info("fallback 第 %d 个模型 %s 成功", i + 1, model_name)
                return result
        except Exception:
            pass
        if not is_last:
            log.warning("模型 %s 失败，尝试下一个... (%d/%d)", model_name, i + 1, len(chain))
    log.error("fallback 链全部 %d 个模型失败", len(chain))
    return None


async def chat_json_with_fallback(system: str, user: str, chain: list[dict], **kw) -> Optional[dict]:
    kw.setdefault("json_mode", True)
    txt = await chat_with_fallback(system, user, chain, **kw)
    if not txt or not txt.strip():
        return None
    obj = _extract_json(txt)
    return obj


def available() -> bool:
    return settings.ai_ready


def stats_dict() -> dict:
    return dict(stats)
