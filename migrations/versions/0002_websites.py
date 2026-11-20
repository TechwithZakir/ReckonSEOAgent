"""Add tenant-scoped websites and DNS verification challenges.

Revision ID: 0002_websites
Revises: 0001_identity_and_tenants
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_websites"
down_revision: str | None = "0001_identity_and_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("scheme", sa.String(length=5), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("ver_tok", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_sites_id_org"),
        sa.UniqueConstraint("org_id", "host", name="uq_sites_org_host"),
    )
    op.create_table(
        "site_create_reqs",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("req_hash", sa.String(length=64), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "idem_key"),
        sa.UniqueConstraint("site_id"),
    )

    op.execute("ALTER TABLE sites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sites FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY site_scope ON sites
        USING (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )
    op.execute("ALTER TABLE site_create_reqs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE site_create_reqs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY site_create_req_scope ON site_create_reqs
        USING (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS site_create_req_scope ON site_create_reqs")
    op.execute("ALTER TABLE site_create_reqs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS site_scope ON sites")
    op.execute("ALTER TABLE sites DISABLE ROW LEVEL SECURITY")
    op.drop_table("site_create_reqs")
    op.drop_table("sites")
