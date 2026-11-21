"""Add verified email, tenant-scoped membership approvals and invitations.

Revision ID: 0015_org_management
Revises: 0014_password_reset
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_org_management"
down_revision: str | None = "0014_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_members",
        sa.Column("version", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
    )
    op.execute(
        """
        CREATE FUNCTION reckon_update_membership_version() RETURNS trigger AS $$
        BEGIN
            NEW.version := gen_random_uuid();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER org_member_version BEFORE UPDATE ON org_members "
        "FOR EACH ROW EXECUTE FUNCTION reckon_update_membership_version()"
    )
    op.add_column(
        "auth_accounts",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE auth_accounts AS a SET email_verified = true "
        "WHERE EXISTS (SELECT 1 FROM auth_events e WHERE e.usr_id = a.usr_id "
        "AND e.action = 'account.created')"
    )
    role = postgresql.ENUM("owner", "admin", "editor", "viewer", name="org_role", create_type=False)
    op.create_table(
        "org_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_usr_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idem_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("approval_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("target_usr_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("role", role, nullable=False),
        sa.Column("target_version", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("org_id", "actor_usr_id", "idem_key", name="uq_org_change_request"),
        sa.UniqueConstraint("org_id", "id", name="uq_org_change_tenant_id"),
        sa.CheckConstraint("action IN ('invite', 'role_change')", name="ck_org_change_action"),
    )
    op.create_table(
        "org_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("inviter_usr_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_usr_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("delivery_state", sa.String(20), nullable=False),
        sa.UniqueConstraint("change_id", name="uq_org_invite_change"),
        sa.ForeignKeyConstraint(
            ["org_id", "change_id"], ["org_changes.org_id", "org_changes.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_org_invite_email", "org_invites", ["email", "expires_at"])
    for table in ("org_changes", "org_invites"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_scope ON {table} "
            "USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid) "
            "WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)"
        )
    op.execute(
        """
        CREATE POLICY org_invite_recipient ON org_invites FOR SELECT
        USING (
            nullif(current_setting('app.org_id', true), '') IS NULL
            AND email = (
                SELECT email FROM auth_accounts
                WHERE usr_id = nullif(current_setting('app.usr_id', true), '')::uuid
                  AND email_verified = true
            )
        )
        """
    )


def downgrade() -> None:
    op.drop_table("org_invites")
    op.drop_table("org_changes")
    op.drop_column("auth_accounts", "email_verified")
    op.execute("DROP TRIGGER org_member_version ON org_members")
    op.execute("DROP FUNCTION reckon_update_membership_version()")
    op.drop_column("org_members", "version")
