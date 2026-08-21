# -*- coding: utf-8 -*-
"""技能自动发现与热插拔。

三层技能：
1. 内置技能（代码内嵌，如天气查询）：直接注册，EXE 打包无歧义。
2. 目录技能（可执行技能包）：扫描 <DATA_DIR>/skills/<技能名>/skill.yaml + handler.py。
3. SkillHub 技能（~/.workbuddy/skills/**/SKILL.md）：转成「LLM 执行器」——把 SKILL.md
   说明书喂给已接入的 AI（DeepSeek）执行，因为 SkillHub 技能是给 AI 看的指令文档、无代码。

每个技能统一挂载：skill_key（调用代号）、api_key（第三方密钥）、enabled、trigger_keywords，
配置持久化在 skills_config.json，飞书与 webui 都能改。

目录技能包约定（放在 <DATA_DIR>/skills/<技能名>/ 下）：
- skill.yaml: {name, description, trigger_keywords}
- handler.py: class SkillHandler: __init__(self, metadata); async execute(self, message, context, user_id=None) -> str
"""
import importlib.util
import os
import re
import threading
import logging

import yaml

from .. import skills_config

log = logging.getLogger("syscenter.skills")

# 技能目录：默认 <DATA_DIR>/skills，可被 SKILLS_DIR 覆盖（可写持久，EXE 重启不丢）
_DEFAULT_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "skills")
SKILLS_ROOT = os.path.abspath(os.environ.get("SKILLS_DIR", _DEFAULT_SKILLS_DIR))

# SkillHub 技能目录（WorkBuddy 的 skills 目录，SKILL.md 格式）
SKILLHUB_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")


def _builtin_handlers() -> dict:
    """内置技能：{name: (metadata, handler_cls)}。"""
    from .weather_builtin import SkillHandler, BUILTIN_META
    return {BUILTIN_META["name"]: (BUILTIN_META, SkillHandler)}


class SkillHubHandler:
    """把 SkillHub 技能（SKILL.md 说明书）交给 AI 执行。"""

    def __init__(self, metadata: dict):
        self.metadata = metadata

    async def execute(self, message: str, context: list = None, user_id: str = None) -> str:
        from .. import ai_client
        md = self._read_skill_md()
        system = (
            "你是一个技能执行助手。请严格按照下面的【技能说明书】完成用户请求，"
            "直接给出可用结果，用中文回答。\n"
            f"技能名：{self.metadata.get('name', '')}\n\n"
            f"【技能说明书】\n{md}"
        )
        api_key = (self.metadata.get("api_key") or "").strip()
        if api_key:
            system += f"\n\n【已配置密钥】{api_key}（如需调用外部接口请使用该密钥）"
        if not ai_client.available():
            return "⚠️ 该技能需要 AI 才能执行，但 AI 未配置（请在设置页开启 AI 并填 Key）。"
        reply = await ai_client.chat(system, message, max_tokens=2000, temperature=0.3, timeout=90.0)
        return reply or "⚠️ 技能执行失败（AI 无返回）。"

    def _read_skill_md(self) -> str:
        path = self.metadata.get("skill_md_path", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:  # noqa: BLE001
            return f"（技能说明书读取失败：{e}）"


def _parse_skill_md(path: str, fallback_name: str) -> tuple[str, str]:
    """从 SKILL.md 提取 (name, description)。frontmatter 用 --- 包裹。"""
    name, desc = fallback_name, ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:  # noqa: BLE001
        return name, desc
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.S)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
            if isinstance(fm, dict):
                name = fm.get("name") or fm.get("title") or name
                desc = fm.get("description") or ""
        except Exception:  # noqa: BLE001
            pass
    return name, desc


def _iter_skill_md(root: str):
    """递归产出所有 SKILL.md 路径（跳过无关目录）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "__pycache__")]
        if "SKILL.md" in filenames:
            yield os.path.join(dirpath, "SKILL.md")


class SkillRegistry:
    def __init__(self, skills_dir: str = SKILLS_ROOT):
        self.skills_dir = skills_dir
        self.skills: dict = {}          # {skill_key: handler}
        self._lock = threading.Lock()

    # ---------- 加载 ----------
    def load_all_skills(self) -> int:
        loaded = 0
        raw = self._collect_raw()
        cfg = skills_config.list_skills()
        new_entries: dict = {}
        raw_ids = {item["skill_id"] for item in raw}
        for item in raw:
            sid = item["skill_id"]
            entry = cfg.get(sid) or {}
            # 首次登记：收集起来，循环结束后一次性落盘
            if sid not in cfg:
                new_entries[sid] = {
                    "key": item["key"], "name": item["name"], "source": item["source"],
                    "enabled": True, "api_key": "", "trigger_keywords": item["trigger_keywords"],
                    "description": item["description"],
                }
            if entry.get("enabled") is False:
                continue
            key = entry.get("key") or item["key"]
            # key 冲突防御：同名 key 已注册时跳过（避免覆盖），记录告警
            if key in self.skills:
                log.warning("[skills] 技能 key「%s」重复（%s 与已注册技能冲突），已跳过", key, sid)
                continue
            name = entry.get("name") or item["name"]
            api_key = skills_config.decrypt_api_key(sid)
            trigger_keywords = entry.get("trigger_keywords") or item["trigger_keywords"]
            meta = {
                "name": name,
                "description": item["description"],
                "trigger_keywords": trigger_keywords,
                "skill_key": key,
                "skill_id": sid,
                "source": item["source"],
                "api_key": api_key,
            }
            meta.update(item.get("extra", {}))
            try:
                self.skills[key] = item["handler_factory"](meta)
                loaded += 1
            except Exception as e:  # noqa: BLE001
                log.warning("[skills] 实例化 %s 失败：%s", key, e)
        if new_entries:
            skills_config.upsert_many(new_entries)
        # 清理磁盘/代码里已不存在的技能配置（如卸载的 SkillHub 技能、删除的目录技能）
        skills_config.prune_stale(raw_ids)
        return loaded

    def _collect_raw(self) -> list:
        """收集三层来源的原始技能（未合并配置）。"""
        raw: list[dict] = []
        # ① 内置
        for name, (meta, cls) in _builtin_handlers().items():
            raw.append({
                "skill_id": f"builtin:{name}",
                "key": meta.get("key") or name,
                "name": name,
                "source": "builtin",
                "description": meta.get("description", ""),
                "trigger_keywords": meta.get("trigger_keywords", []),
                "handler_factory": (lambda m, c=cls: c(m)),
            })
        # ② 目录技能
        raw.extend(self._scan_dir())
        # ③ SkillHub 技能
        raw.extend(self._scan_skillhub())
        return raw

    def _scan_dir(self) -> list:
        out: list[dict] = []
        base = os.path.abspath(self.skills_dir)
        if not os.path.isdir(base):
            return out
        for folder in sorted(os.listdir(base)):
            folder_path = os.path.join(base, folder)
            if not os.path.isdir(folder_path):
                continue
            yaml_path = os.path.join(folder_path, "skill.yaml")
            handler_path = os.path.join(folder_path, "handler.py")
            if not (os.path.isfile(yaml_path) and os.path.isfile(handler_path)):
                continue
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    metadata = yaml.safe_load(f) or {}
            except Exception as e:  # noqa: BLE001
                log.warning("[skills] 读取 %s 失败：%s", yaml_path, e)
                continue
            name = metadata.get("name") or folder
            out.append({
                "skill_id": f"dir:{folder}",
                "key": folder,
                "name": name,
                "source": "dir",
                "description": metadata.get("description", ""),
                "trigger_keywords": metadata.get("trigger_keywords", []),
                "handler_factory": self._dir_handler_factory(handler_path, folder),
            })
        return out

    @staticmethod
    def _dir_handler_factory(handler_path: str, folder: str):
        def factory(meta: dict):
            spec = importlib.util.spec_from_file_location(f"syscenter_skill_{folder}", handler_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("无法加载 handler.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls = getattr(module, "SkillHandler", None)
            if cls is None:
                raise RuntimeError("handler.py 无 SkillHandler 类")
            return cls(meta)
        return factory

    def _scan_skillhub(self) -> list:
        out: list[dict] = []
        if not os.path.isdir(SKILLHUB_ROOT):
            return out
        for md_path in _iter_skill_md(SKILLHUB_ROOT):
            rel = os.path.relpath(md_path, SKILLHUB_ROOT).replace("\\", "/")
            # 去掉末尾 /SKILL.md，剩余路径作为 skill_id 的标识（如 "@ns/slug" 或 "slug"）
            ident = rel[:-len("SKILL.md")].rstrip("/")
            parts = [p for p in ident.split("/") if p]
            slug = parts[-1] if parts else "skill"
            name, desc = _parse_skill_md(md_path, slug)
            out.append({
                "skill_id": f"skillhub:{ident}",
                "key": slug,
                "name": name,
                "source": "skillhub",
                "description": desc,
                "trigger_keywords": [slug],
                "handler_factory": (lambda m, p=md_path: SkillHubHandler({**m, "skill_md_path": p})),
            })
        return out

    def reload(self) -> int:
        with self._lock:
            self.skills.clear()
            return self.load_all_skills()

    # ---------- 查询 ----------
    def get_available_skills(self) -> list:
        out = []
        for key, h in self.skills.items():
            meta = getattr(h, "metadata", {}) or {}
            out.append({
                "name": meta.get("name", key),
                "key": meta.get("skill_key", key),
                "skill_id": meta.get("skill_id", ""),
                "source": meta.get("source", ""),
                "desc": meta.get("description", ""),
                "trigger_keywords": meta.get("trigger_keywords", []),
                "has_api_key": bool((meta.get("api_key") or "").strip()),
            })
        return out

    def has_skill(self, key: str) -> bool:
        return key in self.skills

    def get_skill(self, key: str):
        return self.skills.get(key)

    @staticmethod
    def keyword_match(message: str, skills: list) -> str | None:
        """遍历技能 trigger_keywords，命中即返回技能 key。"""
        msg = message.lower()
        for sk in skills:
            for kw in (sk.get("trigger_keywords") or []):
                if kw and kw.lower() in msg:
                    return sk.get("key") or sk["name"]
        return None


# ---------- 模块级单例 ----------
_registry: SkillRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> SkillRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SkillRegistry(SKILLS_ROOT)
            _registry.load_all_skills()
        return _registry


def init_skills() -> int:
    """应用启动时调用：确保技能目录存在并加载，返回已加载技能数。"""
    os.makedirs(SKILLS_ROOT, exist_ok=True)
    return get_registry().reload()
