# -*- coding: utf-8 -*-
"""数据库层：asyncpg 连接池 + 建表 + 运行时设置读写

方案参考本机 dragons-breath 项目：app_settings 表承载运行时可覆盖配置，
启动时读取并 apply_overrides 到 config.settings，免重启热更新。
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Optional

import asyncpg

from .config import apply_overrides, default_ai_models, settings
from .request_ctx import get_client_ip, get_request_id
from . import secret_vault

log = logging.getLogger("db")

_pool: Optional[asyncpg.Pool] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 告警日志（飞书推送 / 健康检查触发）
CREATE TABLE IF NOT EXISTS alert_log (
    id          BIGSERIAL PRIMARY KEY,
    level       TEXT NOT NULL DEFAULT 'info',   -- info|warning|critical
    source      TEXT NOT NULL DEFAULT '',         -- health|feishu|vps|network|manual
    message     TEXT NOT NULL,
    payload     JSONB,
    ts          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_log(ts DESC);

-- VPS / 代理矩阵实例配置（持久化，前端维护）
CREATE TABLE IF NOT EXISTS vps_instances (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    host        TEXT NOT NULL,
    port        INT NOT NULL DEFAULT 22,
    kind        TEXT NOT NULL DEFAULT 'vps',     -- vps|proxy
    note        TEXT,
    enabled     BOOLEAN DEFAULT TRUE,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- AI Token 消耗持久化（与 dragons-breath 计费面板同构）
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id                 BIGSERIAL PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    model              TEXT NOT NULL,
    scenario           TEXT NOT NULL DEFAULT '',
    provider           TEXT NOT NULL DEFAULT '',
    prompt_tokens      INT NOT NULL DEFAULT 0,
    completion_tokens  INT NOT NULL DEFAULT 0,
    ok                 BOOLEAN NOT NULL DEFAULT TRUE,
    latency_ms         INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_ts ON ai_usage_log (ts);

-- 待办记事（飞书 bot "/待办" 指令落库；AI 智能待办与经验沉淀模块复用）
CREATE TABLE IF NOT EXISTS todos (
    id          BIGSERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    done        BOOLEAN NOT NULL DEFAULT FALSE,
    is_sys_scope INTEGER NOT NULL DEFAULT 0,   -- 1=核心系统范畴(运维/网络/NAS/VPS/Docker)
    status      TEXT NOT NULL DEFAULT '未完成', -- 未完成|部分完成|已完成
    suggestion  TEXT,                            -- AI 排障建议（存档）
    created_at  TIMESTAMPTZ DEFAULT now(),
    done_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_todos_done ON todos(done, created_at DESC);

-- AI 诊断历史（诊断后存档，前端可回看 + 一键存为待办）
CREATE TABLE IF NOT EXISTS diagnose_history (
    id          BIGSERIAL PRIMARY KEY,
    log_content TEXT NOT NULL,
    result      TEXT NOT NULL,
    model       TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_diag_ts ON diagnose_history(created_at DESC);

-- 自动化剧本预设（用户保存的 n8n webhook 工作流，便于一键触发与列表管理）
CREATE TABLE IF NOT EXISTS automation_presets (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    workflow     TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- 操作审计日志（登录/登出/改设置/启停服务等高风险动作留痕）
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    actor       TEXT NOT NULL DEFAULT 'admin',
    action      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT '',
    request_id  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);

-- AI 笔记 / 知识库（API Key、技术信息等个人沉淀，供「问 AI」调取）
CREATE TABLE IF NOT EXISTS ai_notes (
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'other',   -- apikey|tech|other
    provider     TEXT NOT NULL DEFAULT '',         -- 仅 apikey 类：deepseek|siliconflow|openai|other
    content      TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '',         -- 逗号分隔
    tested       TEXT NOT NULL DEFAULT 'untested', -- ok|fail|untested|skipped
    test_result  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_notes_ts ON ai_notes(created_at DESC);

-- 自动灾变备份记录（backup.py 落库：full 全量 / incr 增量）
CREATE TABLE IF NOT EXISTS backup_log (
    id           BIGSERIAL PRIMARY KEY,
    backup_type  TEXT NOT NULL,                -- full|incr
    file_path    TEXT,
    file_size    BIGINT NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'success',  -- success|failed
    message      TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_backup_log_ts ON backup_log(created_at DESC);
"""


def _run_alembic_upgrade() -> None:
    """同步执行 Alembic 迁移到 head（由 asyncio.to_thread 调用）。

    数据库地址从 app.config.settings 读取，密码不硬编码。失败时抛出异常，
    由调用方回退到内联建表，保证后端仍可启动。
    """
    from alembic import command
    from alembic.config import Config

    # 资源路径：开发态取 backend/；EXE 冻结态取 SysCenter.exe 所在目录
    # （alembic.ini / migrations 与 exe 同目录，见 syscenter_app.cmd_migrate / _project_root）。
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(base_dir, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("script_location", os.path.join(base_dir, "migrations"))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    command.upgrade(cfg, "head")


async def init_pool():
    global _pool
    if _pool:
        return _pool
    for attempt in range(12):
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.pg_dsn, min_size=2, max_size=10,
                command_timeout=20, timeout=10)
            break
        except Exception as e:
            log.warning("连接 Postgres 失败(%d/12): %s", attempt + 1, str(e)[:100])
            await asyncio.sleep(3)
    if not _pool:
        raise RuntimeError("无法连接 Postgres")
    # 版本化迁移优先（Alembic）；失败时回退内联建表，保证后端可启动
    try:
        await asyncio.to_thread(_run_alembic_upgrade)
    except Exception as e:  # noqa: BLE001
        log.warning("Alembic 迁移失败，回退内联建表: %s", str(e)[:200])
        async with _pool.acquire() as c:
            await c.execute(SCHEMA)
            # 老库迁移：补全新增列（CREATE TABLE IF NOT EXISTS 不会加列）
            for table, col, definition in (
                ("todos", "is_sys_scope", "INTEGER NOT NULL DEFAULT 0"),
                ("todos", "status", "TEXT NOT NULL DEFAULT '未完成'"),
                ("todos", "suggestion", "TEXT"),
                ("alert_log", "acknowledged", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ):
                try:
                    await c.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {definition}")
                except Exception as ex:  # noqa: BLE001
                    log.warning("迁移列 %s.%s 失败(可忽略): %s", table, col, str(ex)[:80])
    # 笔记表：无论 alembic 是否成功都确保存在（CREATE TABLE IF NOT EXISTS 幂等）
    try:
        async with _pool.acquire() as c:
            await c.execute(
                "CREATE TABLE IF NOT EXISTS ai_notes ("
                "id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, "
                "category TEXT NOT NULL DEFAULT 'other', provider TEXT NOT NULL DEFAULT '', "
                "content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '', "
                "tested TEXT NOT NULL DEFAULT 'untested', test_result TEXT NOT NULL DEFAULT '', "
                "created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())")
    except Exception as e:  # noqa: BLE001
        log.warning("ai_notes 建表失败(可忽略): %s", str(e)[:120])

    log.info("Postgres 就绪")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if not _pool:
        raise RuntimeError("连接池未初始化")
    return _pool


async def load_runtime_settings():
    """启动时读取 app_settings 并覆盖 config.settings；若为空则写入默认值。"""
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT key, value FROM app_settings")
        raw = {r["key"]: r["value"] for r in rows}
        if not raw:
            # 首次：写入默认模型库与基础开关，便于前端直接改
            defaults = {
                "ai_models": json.dumps(default_ai_models(), ensure_ascii=False),
                "ai_active": settings.ai_active,
                "scenario_models": json.dumps({}, ensure_ascii=False),
                "feishu_enabled": str(settings.feishu_enabled),
                "automation_enabled": str(settings.automation_enabled),
                "health_check_enabled": str(settings.health_check_enabled),
                "health_check_interval": str(settings.health_check_interval),
                "alert_cpu_threshold": str(settings.alert_cpu_threshold),
                "alert_ram_threshold": str(settings.alert_ram_threshold),
                "alert_disk_threshold": str(settings.alert_disk_threshold),
                "lan_subnet": settings.lan_subnet or "",
                "nas_host": settings.nas_host or "",
                "nas_port": str(settings.nas_port),
                "tv_host": settings.tv_host or "",
            }
            for k, v in defaults.items():
                await c.execute(
                    "INSERT INTO app_settings(key, value, updated_at) VALUES($1,$2,now()) "
                    "ON CONFLICT (key) DO NOTHING", k, v)
            raw = defaults
        apply_overrides(raw)
    log.info("运行时设置已加载：ai_enabled=%s feishu_enabled=%s", settings.ai_enabled, settings.feishu_enabled)


# ---------------- 运行时设置读写 ----------------
async def upsert_setting(key: str, value: str):
    async with pool().acquire() as c:
        await c.execute(
            """INSERT INTO app_settings(key, value, updated_at) VALUES($1,$2,now())
               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
            key, value)


async def get_all_settings() -> dict:
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


# ---------------- 告警日志 ----------------
async def save_alert(level: str, source: str, message: str, payload: dict | None = None):
    try:
        async with pool().acquire() as c:
            await c.execute(
                """INSERT INTO alert_log(level, source, message, payload)
                   VALUES($1,$2,$3,$4)""",
                level, source, message, json.dumps(payload or {}, ensure_ascii=False))
    except Exception as e:
        log.warning("写告警日志失败(忽略): %s", str(e)[:120])


async def open_alert_exists(level: str, source: str, message: str) -> bool:
    """是否存在未确认的同类告警（用于去重，避免重复刷屏）。"""
    async with pool().acquire() as c:
        row = await c.fetchval(
            "SELECT 1 FROM alert_log WHERE level=$1 AND source=$2 AND message=$3 "
            "AND acknowledged=FALSE LIMIT 1",
            level, source, message)
    return row is not None


async def recent_alerts(limit: int = 50, include_ack: bool = True) -> list[dict]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id,level,source,message,payload,ts,acknowledged FROM alert_log "
            "ORDER BY ts DESC LIMIT $1", limit)
    out = []
    for r in rows:
        d = dict(r)
        d["ts"] = d["ts"].isoformat() if d.get("ts") else None
        d["acknowledged"] = bool(d.get("acknowledged"))
        if isinstance(d.get("payload"), str):
            try:
                d["payload"] = json.loads(d["payload"])
            except Exception:
                d["payload"] = {}
        out.append(d)
    return out


# ---------------- VPS 实例 ----------------
async def list_vps() -> list[dict]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id,name,host,port,kind,note,enabled,updated_at FROM vps_instances ORDER BY id")
    return [{**dict(r), "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None}
            for r in rows]


async def upsert_vps(item: dict) -> int:
    async with pool().acquire() as c:
        if item.get("id"):
            await c.execute(
                """UPDATE vps_instances SET name=$2,host=$3,port=$4,kind=$5,note=$6,enabled=$7,updated_at=now()
                   WHERE id=$1""",
                item["id"], item["name"], item["host"], int(item.get("port", 22)),
                item.get("kind", "vps"), item.get("note", ""), bool(item.get("enabled", True)))
            return item["id"]
        row = await c.fetchrow(
            """INSERT INTO vps_instances(name,host,port,kind,note,enabled)
               VALUES($1,$2,$3,$4,$5,$6) RETURNING id""",
            item["name"], item["host"], int(item.get("port", 22)),
            item.get("kind", "vps"), item.get("note", ""), bool(item.get("enabled", True)))
        return row["id"]


async def delete_vps(vid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("DELETE FROM vps_instances WHERE id=$1", vid)
        return "DELETE 1" in str(r).upper()


# ---------------- AI 用量 ----------------
async def log_ai_usage(model: str, scenario: str, provider: str,
                       prompt_tokens: int, completion_tokens: int, ok: bool, latency_ms: int = 0):
    try:
        async with pool().acquire() as c:
            await c.execute(
                """INSERT INTO ai_usage_log(model,scenario,provider,prompt_tokens,completion_tokens,ok,latency_ms)
                   VALUES($1,$2,$3,$4,$5,$6,$7)""",
                model, scenario, provider, prompt_tokens, completion_tokens, ok, latency_ms)
    except Exception:
        pass


async def ai_usage_summary(days: int = 30) -> dict:
    cutoff = datetime.now() - __import__("datetime").timedelta(days=days)
    async with pool().acquire() as c:
        rows = await c.fetch(
            """SELECT date_trunc('day', ts AT TIME ZONE 'Asia/Shanghai')::date AS day,
                      model, SUM(prompt_tokens)::bigint AS prompt_tokens,
                      SUM(completion_tokens)::bigint AS completion_tokens,
                      COUNT(*)::int AS calls
               FROM ai_usage_log WHERE ts >= $1
               GROUP BY day, model ORDER BY day DESC, calls DESC""", cutoff)
        totals = await c.fetchrow(
            """SELECT COALESCE(SUM(prompt_tokens),0)::bigint AS p,
                      COALESCE(SUM(completion_tokens),0)::bigint AS c,
                      COUNT(*)::int AS calls,
                      COALESCE(SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END)::int, 0) AS fails
               FROM ai_usage_log WHERE ts >= $1""", cutoff)
    return {"rows": [dict(r) for r in rows],
            "totals": dict(totals) if totals else {"p": 0, "c": 0, "calls": 0, "fails": 0}}


# ---------------- 待办记事（AI 智能待办与经验沉淀模块） ----------------
def _row_to_todo(r) -> dict:
    d = dict(r)
    d["is_sys_scope"] = bool(d.get("is_sys_scope"))
    d["done"] = bool(d.get("done"))
    for k in ("created_at", "done_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    return d


async def add_todo(content: str, is_sys_scope: int = 0, status: str = "未完成") -> int:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO todos(content, done, is_sys_scope, status) VALUES($1, FALSE, $2, $3) "
            "RETURNING id", content, int(is_sys_scope), status)
    return row["id"]


async def get_todo(tid: int) -> dict | None:
    async with pool().acquire() as c:
        row = await c.fetchrow("SELECT * FROM todos WHERE id=$1", tid)
    return _row_to_todo(row) if row else None


async def list_todos(only_open: bool = True, limit: int = 100, query: str = "") -> list[dict]:
    async with pool().acquire() as c:
        if query:
            like = f"%{query}%"
            rows = await c.fetch(
                "SELECT * FROM todos WHERE content LIKE $1 OR suggestion LIKE $1 "
                "ORDER BY created_at DESC LIMIT $2", like, limit)
        elif only_open:
            rows = await c.fetch(
                "SELECT * FROM todos WHERE NOT done ORDER BY created_at DESC LIMIT $1", limit)
        else:
            rows = await c.fetch(
                "SELECT * FROM todos ORDER BY done, created_at DESC LIMIT $1", limit)
    return [_row_to_todo(r) for r in rows]


async def update_todo_status(tid: int, status: str) -> bool:
    done = (status == "已完成")
    async with pool().acquire() as c:
        r = await c.execute(
            "UPDATE todos SET status=$2, done=$3 WHERE id=$1", tid, status, done)
        return "UPDATE 1" in str(r).upper()


async def update_todo_suggestion(tid: int, suggestion: str) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("UPDATE todos SET suggestion=$2 WHERE id=$1", tid, suggestion)
        return "UPDATE 1" in str(r).upper()


async def experience_corpus(limit: int = 50) -> list[dict]:
    """取核心系统范畴且已完成或有 AI 建议的历史，供经验提炼。"""
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT content, suggestion FROM todos "
            "WHERE is_sys_scope=1 AND (status='已完成' OR suggestion IS NOT NULL) LIMIT $1",
            limit)
    return [dict(r) for r in rows]


async def done_todo(tid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute(
            "UPDATE todos SET done=TRUE, done_at=now(), status='已完成' WHERE id=$1 AND NOT done", tid)
        return "UPDATE 1" in str(r).upper()


async def delete_todo(tid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("DELETE FROM todos WHERE id=$1", tid)
    return "DELETE 1" in str(r).upper()


# ---------------- AI 笔记 / 知识库 ----------------
# 敏感类笔记（密钥 / 验证码）：内容加密落库、读取时解密
SECRET_CATEGORIES = {"apikey", "code"}


def _row_to_note(r) -> dict:
    d = dict(r)
    d["tags"] = [t.strip() for t in (d.get("tags") or "").split(",") if t.strip()]
    # P1-02：敏感类（apikey/code）笔记内容读取时解密（旧明文自动兼容）
    if d.get("category") in SECRET_CATEGORIES:
        d["content"] = secret_vault.decrypt_str(d.get("content"))
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
    return d


async def add_note(title: str, category: str, provider: str, content: str,
                  tags, tested: str = "untested", test_result: str = "") -> int:
    tag_str = ",".join(tags) if isinstance(tags, (list, tuple)) else (tags or "")
    # P1-02：敏感类（apikey/code）笔记内容入库前加密
    if category in SECRET_CATEGORIES:
        content = secret_vault.encrypt_str(content)
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO ai_notes(title, category, provider, content, tags, tested, test_result) "
            "VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id",
            title, category, provider, content, tag_str, tested, test_result)
    return row["id"]


async def get_note(nid: int) -> dict | None:
    async with pool().acquire() as c:
        row = await c.fetchrow("SELECT * FROM ai_notes WHERE id=$1", nid)
    return _row_to_note(row) if row else None


async def list_notes(q: str = "", category: str = "", limit: int = 100) -> list[dict]:
    """按标题/内容/标签关键词检索笔记（中文按连续字、英文按词分词，任一命中即匹配）。"""
    clauses: list[str] = []
    params: list = []
    if category:
        clauses.append(f"category=${len(params) + 1}")
        params.append(category)
    if q:
        toks = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", q)
        if toks:
            sub = []
            for t in toks:
                like = f"%{t}%"
                sub.append(f"(title ILIKE ${len(params) + 1} OR content ILIKE ${len(params) + 1} "
                           f"OR tags ILIKE ${len(params) + 1})")
                params.append(like)
            clauses.append("(" + " OR ".join(sub) + ")")
    sql = "SELECT * FROM ai_notes"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
    params.append(limit)
    async with pool().acquire() as c:
        rows = await c.fetch(sql, *params)
    return [_row_to_note(r) for r in rows]


async def update_note(nid: int, **fields) -> bool:
    allowed = {"title", "category", "provider", "content", "tags", "tested", "test_result"}
    sets: list[str] = []
    params: list = []
    category = fields.get("category")
    for k, v in fields.items():
        if k in allowed and v is not None:
            if k == "tags" and isinstance(v, (list, tuple)):
                v = ",".join(v)
            # P1-02：若更新内容且为敏感类（apikey/code），写入前加密
            if k == "content" and (category in SECRET_CATEGORIES):
                v = secret_vault.encrypt_str(v)
            sets.append(f"{k}=${len(params) + 1}")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_at=now()")
    params.append(nid)
    async with pool().acquire() as c:
        r = await c.execute(f"UPDATE ai_notes SET {', '.join(sets)} WHERE id=${len(params)}", *params)
    return "UPDATE 1" in str(r).upper()


async def delete_note(nid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("DELETE FROM ai_notes WHERE id=$1", nid)
    return "DELETE 1" in str(r).upper()


# ---------------- 告警确认/删除 ----------------
async def acknowledge_alert(aid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("UPDATE alert_log SET acknowledged=TRUE WHERE id=$1", aid)
        return "UPDATE 1" in str(r).upper()


async def delete_alert(aid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("DELETE FROM alert_log WHERE id=$1", aid)
        return "DELETE 1" in str(r).upper()


# ---------------- AI 诊断历史 ----------------
async def add_diagnose(log_content: str, result: str, model: str | None) -> int:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO diagnose_history(log_content, result, model) VALUES($1,$2,$3) RETURNING id",
            log_content, result, model)
    return row["id"]


async def list_diagnoses(limit: int = 50) -> list[dict]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id, log_content, result, model, created_at FROM diagnose_history "
            "ORDER BY created_at DESC LIMIT $1", limit)
    return [{**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in rows]


# ---------------- 自动化剧本预设 ----------------
async def add_preset(name: str, workflow: str, payload_json: str) -> int:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO automation_presets(name, workflow, payload_json) VALUES($1,$2,$3) RETURNING id",
            name, workflow, payload_json)
    return row["id"]


async def get_preset(pid: int) -> dict | None:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT id, name, workflow, payload_json FROM automation_presets WHERE id=$1", pid)
    return dict(row) if row else None


async def list_presets() -> list[dict]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id, name, workflow, payload_json, created_at FROM automation_presets ORDER BY id")
    return [{**dict(r), "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in rows]


async def delete_preset(pid: int) -> bool:
    async with pool().acquire() as c:
        r = await c.execute("DELETE FROM automation_presets WHERE id=$1", pid)
        return "DELETE 1" in str(r).upper()


# ---------------- 操作审计日志 ----------------
async def add_audit(actor: str = "admin", action: str = "", target: str = "", detail: str = "",
                    ip: str | None = None, request_id: str | None = None):
    """记录一次高风险操作（最佳努力，失败仅告警不阻断业务）。

    ip / request_id 缺省时从请求上下文（中间件设置的 contextvar）取。
    """
    try:
        async with pool().acquire() as c:
            await c.execute(
                """INSERT INTO audit_log(actor, action, target, detail, ip, request_id)
                   VALUES($1,$2,$3,$4,$5,$6)""",
                actor, action, target, detail,
                ip if ip is not None else get_client_ip(),
                request_id if request_id is not None else get_request_id())
    except Exception as e:  # noqa: BLE001
        log.warning("写审计日志失败(忽略): %s", str(e)[:120])


async def recent_audits(limit: int = 200) -> list[dict]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id, ts, actor, action, target, detail, ip, request_id "
            "FROM audit_log ORDER BY ts DESC LIMIT $1", limit)
    return [{**dict(r), "ts": r["ts"].isoformat() if r.get("ts") else None} for r in rows]
