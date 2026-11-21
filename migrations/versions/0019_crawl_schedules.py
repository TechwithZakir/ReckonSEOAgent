"""Add tenant-scoped crawl schedules.

Revision ID: 0019_crawl_schedules
Revises: 0018_native_mfa
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0019_crawl_schedules"
down_revision: str | None = "0018_native_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crawl_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_usr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("frequency IN ('daily', 'weekly')", name="ck_crawl_schedule_frequency"),
        sa.UniqueConstraint("org_id", "site_id", name="uq_crawl_schedule_org_site"),
        sa.ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
    )
    op.execute("ALTER TABLE crawl_schedules ALTER COLUMN active DROP DEFAULT")
    op.create_index(
        "ix_crawl_schedules_next_active",
        "crawl_schedules",
        ["active", "next_run_at"],
    )
    op.execute("ALTER TABLE crawl_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crawl_schedules FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY crawl_schedules_scope ON crawl_schedules
        USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS crawl_schedules_scope ON crawl_schedules")
    op.execute("ALTER TABLE crawl_schedules DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_crawl_schedules_next_active", table_name="crawl_schedules")
    op.drop_table("crawl_schedules")
