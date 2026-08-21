"""backup_log 表：自动灾变备份记录

Revision ID: 0004_backup_log
Revises: 0003_ai_notes

记录每次全量/增量备份的执行结果（类型、归档路径、体积、状态、信息），
供调度周期判断（上次全量/增量时间）与前端状态查询。
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0004_backup_log"
down_revision = "0003_ai_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        """
        CREATE TABLE IF NOT EXISTS backup_log (
            id           BIGSERIAL PRIMARY KEY,
            backup_type  TEXT NOT NULL,                -- full|incr
            file_path    TEXT,
            file_size    BIGINT NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'success',  -- success|failed
            message      TEXT NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ DEFAULT now()
        )
        """
    ))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_backup_log_ts ON backup_log(created_at DESC)"))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS backup_log"))
