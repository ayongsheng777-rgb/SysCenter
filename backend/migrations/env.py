# -*- coding: utf-8 -*-
"""Alembic 环境：从环境变量/.env 读取数据库地址（不硬编码密码）。

设计要点：
- 迁移使用 psycopg2 同步驱动连接同一 Postgres。运行时连接池仍用 asyncpg，
  二者共用同一连接参数（密码来自环境变量/ .env，不入库）。
- 注意：必须在 load_dotenv() 之后、从 os.getenv 直接拼 DSN，而非读取
  config.settings 单例（该单例在 import 时已固化默认值，load_dotenv 不会刷新它）。
- target_metadata 留空：本项目用原始 SQL 建表，不依赖 ORM 模型；迁移文件手写
  显式 SQL，全部 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，幂等、绝不删数据。
"""
import os

# 先加载 .env（若存在），确保后续 os.getenv 读到真实 PG 密码
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

# 与 backend/app/config.py 的默认值保持一致，从环境变量（已含 .env）直接拼 DSN
_pg_user = os.getenv("PG_USER", "syscenter")
_pg_password = os.getenv("PG_PASSWORD", "syscenter_pass_2026")
_pg_host = os.getenv("PG_HOST", "127.0.0.1")
_pg_port = os.getenv("PG_PORT", "5442")
_pg_database = os.getenv("PG_DATABASE", "syscenter")
_PG_URL = (
    f"postgresql+psycopg2://{_pg_user}:{_pg_password}"
    f"@{_pg_host}:{_pg_port}/{_pg_database}"
)
config.set_main_option("sqlalchemy.url", _PG_URL)

# 配置日志（若配置文件存在）
if config.config_file_name is not None:
    try:
        from logging.config import fileConfig

        fileConfig(config.config_file_name)
    except Exception:
        pass

# 本项目不使用 ORM 自动生成
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库（如 `alembic upgrade head --sql`）。"""
    context.configure(
        url=_PG_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_name="postgresql",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：用 psycopg2 同步引擎连接数据库执行迁移。"""
    connectable = create_engine(_PG_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
