# -*- coding: utf-8 -*-
"""全局配置：环境变量 -> 强类型配置对象

运行时设置（AI 模型、飞书接入、监控目标等）可由前端在 /api/settings 修改，
落库 app_settings 后通过 apply_overrides() 覆盖 env 初始值，免重启热更新。
方案参考本机 dragons-breath 项目。
"""
import json
import os
import threading
from dataclasses import dataclass, field

# 加载项目根目录 .env（docker-compose 与后端共享同一份；密码不入库、不进 config 默认值）
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")))
except Exception:  # noqa: BLE001
    pass

# 轮循计数器：{scenario: int}，线程安全
_RR_LOCK = threading.Lock()
_ROUND_ROBIN: dict[str, int] = {}


def _get_rr() -> dict[str, int]:
    return _ROUND_ROBIN


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _b(key: str, default: bool = False) -> bool:
    return str(os.getenv(key, str(default))).strip().lower() in ("1", "true", "yes", "on")


def _list(key: str, default: list | None = None) -> list:
    """逗号分隔环境变量 -> 字符串列表（去空）。"""
    raw = os.getenv(key, "")
    if not raw:
        return list(default or [])
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    # --- 服务 ---
    backend_host: str = field(default_factory=lambda: os.getenv("BACKEND_HOST", "0.0.0.0"))
    backend_port: int = field(default_factory=lambda: _i("BACKEND_PORT", 8352))

    # --- 数据目录（OTP 密钥等落盘处）---
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")))

    # --- Postgres ---
    pg_host: str = field(default_factory=lambda: os.getenv("PG_HOST", "127.0.0.1"))
    pg_port: int = field(default_factory=lambda: _i("PG_PORT", 5442))
    pg_user: str = field(default_factory=lambda: os.getenv("PG_USER", "syscenter"))
    pg_password: str = field(default_factory=lambda: os.getenv("PG_PASSWORD", "syscenter_pass_2026"))
    pg_database: str = field(default_factory=lambda: os.getenv("PG_DATABASE", "syscenter"))

    # --- Redis ---
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "127.0.0.1"))
    redis_port: int = field(default_factory=lambda: _i("REDIS_PORT", 6387))
    redis_db: int = field(default_factory=lambda: _i("REDIS_DB", 0))

    # --- AI 诊断大脑（默认 DeepSeek，参考指南）---
    ai_enabled: bool = field(default_factory=lambda: _b("AI_ENABLED", False))
    ai_base_url: str = field(default_factory=lambda: os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1"))
    ai_api_key: str = field(default_factory=lambda: os.getenv("AI_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "deepseek-chat"))
    ai_proxy: str = field(default_factory=lambda: os.getenv("AI_PROXY", ""))
    ai_user_agent: str = field(default_factory=lambda: os.getenv("AI_USER_AGENT", ""))
    # 多模型（前端维护）：[{id,name,base_url,model,api_key,tags,user_agent,proxy}]
    ai_models: list = field(default_factory=list)
    ai_active: str = field(default_factory=lambda: os.getenv("AI_ACTIVE", "default"))
    # 场景模型映射：{scenario: "id1,id2"}，逗号分隔=轮循链，单值=固定
    scenario_models: dict = field(default_factory=dict)

    # --- 飞书自定义机器人（告警推送，参考指南 + 本机方案，支持 HMAC 签名）---
    feishu_enabled: bool = field(default_factory=lambda: _b("FEISHU_ENABLED", False))
    feishu_webhook: str = field(default_factory=lambda: os.getenv("FEISHU_WEBHOOK", ""))
    feishu_secret: str = field(default_factory=lambda: os.getenv("FEISHU_SECRET", ""))
    feishu_default_chat: str = field(default_factory=lambda: os.getenv("FEISHU_DEFAULT_CHAT", ""))

    # --- 飞书 bot 智能体（WebSocket 长连接，双向通讯，对齐 OmniCraft）---
    # 自建应用凭据；门禁白名单为 open_id 列表（私聊首条自动配对，见 feishu.py）
    feishu_app_id: str = field(default_factory=lambda: os.getenv("FEISHU_APP_ID", ""))
    feishu_app_secret: str = field(default_factory=lambda: os.getenv("FEISHU_APP_SECRET", ""))
    feishu_admin_users: list = field(default_factory=lambda: _list("FEISHU_ADMIN_USERS"))
    feishu_trusted_bots: list = field(default_factory=lambda: _list("FEISHU_TRUSTED_BOTS"))

    # --- 自动化剧本中枢（n8n webhook）---
    automation_enabled: bool = field(default_factory=lambda: _b("AUTOMATION_ENABLED", False))
    n8n_webhook_base: str = field(default_factory=lambda: os.getenv("N8N_WEBHOOK_BASE", ""))

    # --- 监控目标（NAS / tv 盒子 / 局域网网段），可运行时改 ---
    lan_subnet: str = field(default_factory=lambda: os.getenv("LAN_SUBNET", ""))
    nas_host: str = field(default_factory=lambda: os.getenv("NAS_HOST", ""))
    nas_port: int = field(default_factory=lambda: _i("NAS_PORT", 5000))
    tv_host: str = field(default_factory=lambda: os.getenv("TV_HOST", ""))

    # --- 系统体检 / 定时告警 ---
    health_check_enabled: bool = field(default_factory=lambda: _b("HEALTH_CHECK_ENABLED", True))
    health_check_interval: int = field(default_factory=lambda: _i("HEALTH_CHECK_INTERVAL", 300))
    alert_cpu_threshold: int = field(default_factory=lambda: _i("ALERT_CPU_THRESHOLD", 90))
    alert_ram_threshold: int = field(default_factory=lambda: _i("ALERT_RAM_THRESHOLD", 90))
    alert_disk_threshold: int = field(default_factory=lambda: _i("ALERT_DISK_THRESHOLD", 90))

    @property
    def pg_dsn(self) -> str:
        return (f"postgresql://{self.pg_user}:{self.pg_password}"
                f"@{self.pg_host}:{self.pg_port}/{self.pg_database}")

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def ai_ready(self) -> bool:
        p = self.active_ai_profile()
        k = (p.get("api_key") or "").strip()
        if not self.ai_enabled or not k:
            return False
        placeholders = ("your", "xxx", "sk-xxx", "changeme", "placeholder", "todo")
        return not any(pl in k.lower() for pl in placeholders)

    def active_ai_profile(self) -> dict:
        models = getattr(self, "ai_models", None) or []
        active = getattr(self, "ai_active", "default")
        for m in models:
            if m.get("id") == active:
                return m
        return {
            "id": "default", "name": "默认模型",
            "base_url": self.ai_base_url, "model": self.ai_model,
            "api_key": self.ai_api_key, "tags": [],
            "user_agent": getattr(self, "ai_user_agent", ""),
            "proxy": getattr(self, "ai_proxy", ""),
        }

    def get_scenario_fallback_chain(self, scenario: str) -> list[dict]:
        """返回场景的轮循模型链 + 默认模型兜底。"""
        models = getattr(self, "ai_models", None) or []
        sid = (self.scenario_models or {}).get(scenario, "")
        chain: list[dict] = []
        if sid:
            ids = [x.strip() for x in sid.split(",") if x.strip()]
            for mid in ids:
                for m in models:
                    if m.get("id") == mid:
                        prof = dict(m)
                        prof["scenario"] = scenario
                        chain.append(prof)
                        break
            if len(chain) > 1:
                _RR_LOCK.acquire()
                try:
                    _ROUND_ROBIN.setdefault(scenario, 0)
                    offset = _ROUND_ROBIN[scenario] % len(chain)
                    _ROUND_ROBIN[scenario] += 1
                finally:
                    _RR_LOCK.release()
                chain = chain[offset:] + chain[:offset]
        fallback = self.active_ai_profile()
        fallback["scenario"] = scenario
        if not any(p.get("id") == fallback.get("id", "") for p in chain):
            chain.append(fallback)
        return chain


settings = Settings()


# ============ 运行时可覆盖键（白名单） ============
RUNTIME_KEYS = {
    # AI 模型接入
    "ai_enabled": bool, "ai_base_url": str, "ai_api_key": str, "ai_model": str,
    "ai_proxy": str, "ai_user_agent": str,
    "ai_models": list, "ai_active": str, "scenario_models": dict,
    # 飞书
    "feishu_enabled": bool, "feishu_webhook": str, "feishu_secret": str, "feishu_default_chat": str,
    "feishu_app_id": str, "feishu_app_secret": str,
    "feishu_admin_users": list, "feishu_trusted_bots": list,
    # 自动化
    "automation_enabled": bool, "n8n_webhook_base": str,
    # 监控目标
    "lan_subnet": str, "nas_host": str, "nas_port": int, "tv_host": str,
    # 体检/告警
    "health_check_enabled": bool, "health_check_interval": int,
    "alert_cpu_threshold": int, "alert_ram_threshold": int, "alert_disk_threshold": int,
}

# 密钥类键：GET 时脱敏，PUT 时若收到脱敏占位符则保留原值不覆盖
SECRET_KEYS = {"ai_api_key", "feishu_secret", "feishu_app_secret"}
_MASK = "****"


def apply_overrides(raw: dict):
    """用运行时设置覆盖 env 初始值。raw 形如 {key: json_str | 原生值}。"""
    for k, typ in RUNTIME_KEYS.items():
        if k not in raw:
            continue
        v = raw[k]
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                pass
        if v is None:
            continue
        try:
            if typ is bool:
                v = bool(v)
            elif typ is int:
                v = int(v)
            elif typ is float:
                v = float(v)
        except (TypeError, ValueError):
            continue
        setattr(settings, k, v)


def mask_secret(val) -> str:
    s = "" if val is None else str(val)
    if not s:
        return ""
    return _MASK + s[-4:] if len(s) > 4 else _MASK


def _mask_profile(p: dict) -> dict:
    p = dict(p or {})
    if p.get("api_key"):
        p["api_key"] = mask_secret(p["api_key"])
    return p


def runtime_dict() -> dict:
    """当前生效的运行时设置（密钥脱敏），供前端设置页渲染。"""
    out = {}
    for k in RUNTIME_KEYS:
        v = getattr(settings, k, None)
        if k in SECRET_KEYS:
            v = mask_secret(v) if v else ""
        if k == "ai_models":
            v = [_mask_profile(x) for x in (v or [])]
        out[k] = v
    return out


# 硅基流动（SiliconFlow）OpenAI 兼容端点：国内节点，proxy 必须留空
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"


def default_ai_models() -> list:
    """首次启动的默认模型库：DeepSeek 为主，硅基流动(SiliconFlow)为可选国内节点。

    说明：源码里硅基流动条目的 api_key 留空（密钥不进 git）；实际 key 由前端填写或
    运行时写入 app_settings.ai_models。已配置 key 的部署不受影响（DB 非空时本函数不被调用）。
    """
    return [
        {"id": "deepseek", "name": "DeepSeek (云端推理)", "base_url": "https://api.deepseek.com/v1",
         "model": "deepseek-chat", "api_key": settings.ai_api_key or "", "tags": ["diagnose", "primary"],
         "user_agent": "", "proxy": settings.ai_proxy or ""},
        {"id": "siliconflow-deepseek-v3", "name": "硅基流动 DeepSeek-V3", "base_url": SILICONFLOW_BASE_URL,
         "model": "deepseek-ai/DeepSeek-V3", "api_key": "", "tags": ["diagnose", "primary"],
         "user_agent": "", "proxy": ""},
        {"id": "siliconflow-deepseek-r1", "name": "硅基流动 DeepSeek-R1 (推理)", "base_url": SILICONFLOW_BASE_URL,
         "model": "deepseek-ai/DeepSeek-R1", "api_key": "", "tags": ["diagnose", "reasoning"],
         "user_agent": "", "proxy": ""},
        {"id": "siliconflow-qwen3-32b", "name": "硅基流动 Qwen3-32B", "base_url": SILICONFLOW_BASE_URL,
         "model": "Qwen/Qwen3-32B", "api_key": "", "tags": ["diagnose"],
         "user_agent": "", "proxy": ""},
        {"id": "siliconflow-qwen3-8b", "name": "硅基流动 Qwen3-8B (轻量)", "base_url": SILICONFLOW_BASE_URL,
         "model": "Qwen/Qwen3-8B", "api_key": "", "tags": ["diagnose", "fast"],
         "user_agent": "", "proxy": ""},
    ]
