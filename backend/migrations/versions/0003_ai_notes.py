"""ai_notes 正式纳入版本化迁移

Revision ID: 0003_ai_notes
Revises: 0002_audit_log

此前 ai_notes 仅由 db.py 的 init_pool 通过 CREATE TABLE IF NOT EXISTS 补建，
导致 Alembic schema ≠ 实际 schema。本迁移将其纳入正式迁移体系（P2-04）。
幂等：全新库建表；已有库（db.py 已补建）跳过。
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0003_ai_notes"
down_revision = "0002_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ai_notes (
            id           BIGSERIAL PRIMARY KEY,
            title        TEXT NOT NULL,
            category     TEXT NOT NULL DEFAULT 'other',
            provider     TEXT NOT NULL DEFAULT '',
            content      TEXT NOT NULL,
            tags         TEXT NOT NULL DEFAULT '',
            tested       TEXT NOT NULL DEFAULT 'untested',
            test_result  TEXT NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ DEFAULT now(),
            updated_at   TIMESTAMPTZ DEFAULT now()
        )
        """
    ))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_ai_notes_ts ON ai_notes(created_at DESC)"))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ai_notes"))
