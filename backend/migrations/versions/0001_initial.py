# -*- coding: utf-8 -*-
"""初始 schema（镜像原 db.py 的 SCHEMA，补齐历史 ALTER 新增列）

幂等设计（全部 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS）：
- 全新库：直接建全量表（含 is_sys_scope / status / suggestion / acknowledged 列）
- 已有库：CREATE TABLE 跳过已存在表，仅通过 ALTER 补齐历史上由 init_pool
  的 ALTER 语句新增的列，绝不删数据、不改动既有行
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_log (
    id          BIGSERIAL PRIMARY KEY,
    level       TEXT NOT NULL DEFAULT 'info',   -- info|warning|critical
    source      TEXT NOT NULL DEFAULT '',         -- health|feishu|vps|network|manual
    message     TEXT NOT NULL,
    payload     JSONB,
    ts          TIMESTAMPTZ DEFAULT now(),
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_log(ts DESC);

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

CREATE TABLE IF NOT EXISTS diagnose_history (
    id          BIGSERIAL PRIMARY KEY,
    log_content TEXT NOT NULL,
    result      TEXT NOT NULL,
    model       TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_diag_ts ON diagnose_history(created_at DESC);

CREATE TABLE IF NOT EXISTS automation_presets (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    workflow     TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT now()
);
"""

# 历史上由 init_pool 的 ALTER 语句补齐的列；对旧库幂等补齐，对新库无副作用
ALTERS = [
    ("todos", "is_sys_scope", "INTEGER NOT NULL DEFAULT 0"),
    ("todos", "status", "TEXT NOT NULL DEFAULT '未完成'"),
    ("todos", "suggestion", "TEXT"),
    ("alert_log", "acknowledged", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def upgrade() -> None:
    op.execute(text(SCHEMA))
    for table, col, definition in ALTERS:
        op.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {definition}"))


def downgrade() -> None:
    # 注意：downgrade 会删除全部业务表与数据，仅在确需回滚到“无 schema”时使用
    op.execute(text("DROP TABLE IF EXISTS automation_presets"))
    op.execute(text("DROP TABLE IF EXISTS diagnose_history"))
    op.execute(text("DROP TABLE IF EXISTS todos"))
    op.execute(text("DROP TABLE IF EXISTS ai_usage_log"))
    op.execute(text("DROP TABLE IF EXISTS vps_instances"))
    op.execute(text("DROP TABLE IF EXISTS alert_log"))
    op.execute(text("DROP TABLE IF EXISTS app_settings"))
