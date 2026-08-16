"""audit log

Revision ID: 0002_audit_log
Revises: 0001_initial
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_audit_log"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id          BIGSERIAL PRIMARY KEY,
            ts          TIMESTAMPTZ DEFAULT now(),
            actor       TEXT NOT NULL DEFAULT 'admin',
            action      TEXT NOT NULL,
            target      TEXT NOT NULL DEFAULT '',
            detail      TEXT NOT NULL DEFAULT '',
            ip          TEXT NOT NULL DEFAULT '',
            request_id  TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC)")


def downgrade():
    # 破坏性：仅当确需回滚到无审计状态时使用
    op.execute("DROP TABLE IF EXISTS audit_log")
