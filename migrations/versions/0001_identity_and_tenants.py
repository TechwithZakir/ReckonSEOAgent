"""Create identity and tenant membership tables with PostgreSQL RLS.

Revision ID: 0001_identity_and_tenants
Revises:
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity_and_tenants"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

org_role = sa.Enum(
    "owner",
    "admin",
    "editor",
    "viewer",
    name="org_role",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "identities",
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issuer", "subject"),
    )
    op.create_index(
        "ix_identities_usr_id",
        "identities",
        ["usr_id"],
    )
    op.create_table(
        "orgs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "org_members",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", org_role, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "usr_id"),
    )
    op.create_table(
        "org_create_reqs",
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idem_key", sa.String(length=128), nullable=False),
        sa.Column("req_hash", sa.String(length=64), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("usr_id", "idem_key"),
        sa.UniqueConstraint("org_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("res_type", sa.String(length=100), nullable=False),
        sa.Column("res_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("req_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_usr_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_org_created",
        "audit_events",
        ["org_id", "created_at"],
    )

    op.execute("ALTER TABLE orgs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE orgs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_scope ON orgs
        USING (
            id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )
    op.execute("ALTER TABLE org_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_members FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_member_scope ON org_members
        USING (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )
    op.execute("ALTER TABLE org_create_reqs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_create_reqs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_create_req_scope ON org_create_reqs
        USING (
            usr_id = nullif(current_setting('app.usr_id', true), '')::uuid
        )
        WITH CHECK (
            usr_id = nullif(current_setting('app.usr_id', true), '')::uuid
        )
        """
    )
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_event_scope ON audit_events
        USING (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = nullif(current_setting('app.org_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_event_scope ON audit_events")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    op.drop_table("audit_events")
    op.execute(
        "DROP POLICY IF EXISTS org_create_req_scope ON org_create_reqs"
    )
    op.execute("ALTER TABLE org_create_reqs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_member_scope ON org_members")
    op.execute("ALTER TABLE org_members DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_scope ON orgs")
    op.execute("ALTER TABLE orgs DISABLE ROW LEVEL SECURITY")
    op.drop_table("org_members")
    op.drop_table("org_create_reqs")
    op.drop_table("orgs")
    op.drop_index("ix_identities_usr_id", table_name="identities")
    op.drop_table("identities")
    op.drop_table("users")
    org_role.drop(op.get_bind(), checkfirst=True)
