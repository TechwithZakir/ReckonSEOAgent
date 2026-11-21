"""Allow users to discover their own active organization memberships.

Revision ID: 0011_membership_discovery
Revises: 0010_org_model_settings
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011_membership_discovery"
down_revision: str | None = "0010_org_model_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY org_member_own_discovery ON org_members FOR SELECT
        USING (
            nullif(current_setting('app.org_id', true), '') IS NULL
            AND usr_id = nullif(current_setting('app.usr_id', true), '')::uuid
            AND active = true
        )
        """
    )
    op.create_index(
        "ix_org_members_user_active_org", "org_members", ["usr_id", "org_id"],
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_org_members_user_active_org", table_name="org_members")
    op.execute("DROP POLICY IF EXISTS org_member_own_discovery ON org_members")
