# -*- coding: utf-8 -*-
"""敏感信息脱敏器（P2-08）：发给 AI / 记入日志前，剥离密钥类内容

AI 诊断 / AI 问答会把用户粘贴的日志、配置文件、笔记内容直接发给大模型。
这些内容可能包含 IP、Token、API Key、Cookie、密码、内部域名等。
统一经本模块脱敏后再外发，降低凭据泄露风险。
"""
import re

# 顺序匹配；每条替换为 <REDACTED>。覆盖常见密钥形态（不区分大小写）。
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{8,}", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|pwd)\s*[=:]\s*[^\s,'\"]+"),
    re.compile(r"(?i)(access[_-]?key|private[_-]?key)\s*[=:]\s*[^\s,'\"]+"),
    re.compile(r"(?i)gh[pousr]_[A-Za-z0-9]{20,}"),          # GitHub token
    re.compile(r"(?i)AKIA[0-9A-Z]{16}"),                    # AWS access key id
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
]

_MASK = "<REDACTED>"


def redact(text: str | None) -> str:
    """对文本做敏感信息脱敏；非字符串或空值原样返回。"""
    if not text:
        return text or ""
    out = text
    for p in _PATTERNS:
        out = p.sub(_MASK, out)
    return out


def redact_dict(obj: dict, keys=("content", "message", "log", "text", "payload")) -> dict:
    """对字典中指定键的字符串值做脱敏（浅层，不改原对象）。"""
    if not isinstance(obj, dict):
        return obj
    out = dict(obj)
    for k in keys:
        if isinstance(out.get(k), str):
            out[k] = redact(out[k])
    return out
