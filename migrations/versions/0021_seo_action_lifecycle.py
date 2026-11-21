"""Add immutable SEO action approval and execution lifecycle.

Revision ID: 0021_seo_action_lifecycle
Revises: 0020_native_mfa_recovery
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_seo_action_lifecycle"
down_revision: str | None = "0020_native_mfa_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seo_action_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_usr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("idem_key", sa.String(128), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("approval_hash", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("target_url", sa.String(2048), nullable=False),
        sa.Column("target_version", sa.String(64), nullable=False),
        sa.Column("risk", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=False),
        sa.Column("proposed_state", postgresql.JSONB(), nullable=False),
        sa.Column("executed_state", postgresql.JSONB(), nullable=True),
        sa.Column("verification_state", postgresql.JSONB(), nullable=True),
        sa.Column("rollback_state", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_seo_action_risk"),
        sa.CheckConstraint(
            "status IN ('proposed','approved','rejected','executing','executed','verified','failed','rolled_back')",
            name="ck_seo_action_status",
        ),
        sa.UniqueConstraint("org_id", "idem_key", name="uq_seo_action_org_idem"),
        sa.UniqueConstraint("org_id", "id", name="uq_seo_action_tenant_id"),
        sa.ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_seo_action_org_created",
        "seo_action_proposals",
        ["org_id", "created_at"],
    )
    op.execute("ALTER TABLE seo_action_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE seo_action_proposals FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY seo_action_proposals_scope ON seo_action_proposals
        USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS seo_action_proposals_scope ON seo_action_proposals")
    op.execute("ALTER TABLE seo_action_proposals DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_seo_action_org_created",
        table_name="seo_action_proposals",
    )
    op.drop_table("seo_action_proposals")
