"""Add tenant-scoped crawl run and usage records.

Revision ID: 0003_site_crawl_runs
Revises: 0002_websites
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_site_crawl_runs"
down_revision: str | None = "0002_websites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_crawl_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("req_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("req_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_url", sa.String(length=2048), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("bytes_read", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("redirect_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'disallowed', 'failed')",
            name="ck_site_crawl_runs_status",
        ),
        sa.CheckConstraint(
            "bytes_read IS NULL OR bytes_read >= 0",
            name="ck_site_crawl_runs_bytes_read",
        ),
        sa.CheckConstraint(
            "redirect_count IS NULL OR redirect_count >= 0",
            name="ck_site_crawl_runs_redirects",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_usr_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "idem_key",
            name="uq_site_crawl_runs_org_idem",
        ),
    )
    op.create_index(
        "ix_site_crawl_runs_org_started",
        "site_crawl_runs",
        ["org_id", "started_at"],
    )
    op.execute("ALTER TABLE site_crawl_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE site_crawl_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY site_crawl_run_scope ON site_crawl_runs
        USING (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS site_crawl_run_scope ON site_crawl_runs")
    op.execute("ALTER TABLE site_crawl_runs DISABLE ROW LEVEL SECURITY")
    op.drop_table("site_crawl_runs")
