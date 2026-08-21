# -*- coding: utf-8 -*-
"""技能配置存储（skill_key / 第三方 api_key / 启用开关 / 触发词）

持久化到 <DATA_DIR>/skills_config.json（EXE 可写、重启不丢）。
- skill_key：飞书/网页精准调用的唯一代号（如 weather）
- api_key：技能调第三方接口所需的密钥，用 secret_vault 加密后落盘
- enabled：启用开关
- trigger_keywords：触发词（飞书模糊匹配）

配置按 skill_id 索引（稳定标识，不随 skill_key 改名而变）：
  skill_id = "<source>:<原始标识>"，如 "builtin:天气查询"、"dir:weather"、"skillhub:ns/slug"
"""
import json
import os
import threading
import logging

from .config import settings
from . import secret_vault

log = logging.getLogger("syscenter.skills_config")

CONFIG_PATH = os.path.join(settings.data_dir, "skills_config.json")

_lock = threading.Lock()


def _read() -> dict:
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("skills"), dict):
                return data
    except Exception as e:  # noqa: BLE001
        log.warning("[skills_config] 读取失败：%s", e)
    return {"skills": {}}


def _write(data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("[skills_config] 写入失败：%s", e)
        return False


def list_skills() -> dict:
    """返回 {skill_id: entry}，entry 的 api_key 为密文。"""
    with _lock:
        return dict(_read().get("skills") or {})


def get_skill(skill_id: str) -> dict | None:
    with _lock:
        return (_read().get("skills") or {}).get(skill_id)


def upsert_skill(skill_id: str, entry: dict) -> bool:
    """写入/更新某技能配置。entry 需含 key/name/source/enabled/trigger_keywords/api_key(密文)。"""
    with _lock:
        data = _read()
        skills = data.setdefault("skills", {})
        skills[skill_id] = entry
        return _write(data)


def upsert_many(entries: dict) -> bool:
    """批量登记 {skill_id: entry}（仅新增，不覆盖已有，供首次扫描时一次性落盘）。"""
    with _lock:
        data = _read()
        skills = data.setdefault("skills", {})
        for sid, entry in entries.items():
            skills.setdefault(sid, entry)
        return _write(data)


def prune_stale(valid_ids: set) -> bool:
    """清理磁盘/代码里已不存在（不在 valid_ids）的技能配置，返回是否有变更。"""
    with _lock:
        data = _read()
        skills = data.setdefault("skills", {})
        stale = [sid for sid in skills if sid not in valid_ids]
        if not stale:
            return False
        for sid in stale:
            skills.pop(sid, None)
            log.info("[skills_config] 清理已失效技能配置：%s", sid)
        return _write(data)


def decrypt_api_key(skill_id: str) -> str:
    """读取某技能的 api_key 并解密为明文。"""
    entry = get_skill(skill_id)
    if not entry:
        return ""
    return secret_vault.decrypt_str(entry.get("api_key") or "")
