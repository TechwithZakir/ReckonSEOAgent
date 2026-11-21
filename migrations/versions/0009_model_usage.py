"""Add a tenant-scoped model token reservation ledger.

Revision ID: 0009_model_usage
Revises: 0008_sitemap_document_evidence
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_model_usage"
down_revision: str | None = "0008_sitemap_document_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("req_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idem_key", sa.String(128), nullable=False),
        sa.Column("req_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("max_input", sa.BigInteger(), nullable=False),
        sa.Column("max_output", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('reserved', 'settled')", name="ck_model_usage_status"),
        sa.CheckConstraint("max_input > 0 AND max_output > 0", name="ck_model_usage_max"),
        sa.CheckConstraint(
            "(status = 'reserved' AND input_tokens IS NULL AND output_tokens IS NULL "
            "AND settled_at IS NULL) OR "
            "(status = 'settled' AND input_tokens IS NOT NULL AND input_tokens >= 0 "
            "AND output_tokens IS NOT NULL AND output_tokens >= 0 AND settled_at IS NOT NULL)",
            name="ck_model_usage_settlement",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_usr_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "idem_key", name="uq_model_usage_org_idem"),
    )
    op.create_index("ix_model_usage_org_started", "model_usage", ["org_id", "started_at"])
    op.execute("ALTER TABLE model_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_usage FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY model_usage_scope ON model_usage
        USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS model_usage_scope ON model_usage")
    op.execute("ALTER TABLE model_usage DISABLE ROW LEVEL SECURITY")
    op.drop_table("model_usage")
