"""Add native account, verification, session and rate-limit storage.

Revision ID: 0012_native_auth
Revises: 0011_membership_discovery
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_native_auth"
down_revision: str | None = "0011_membership_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_accounts",
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("pw_hash", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("usr_id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_verify",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_verify_expiry", "auth_verify", ["expires_at"])
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_expiry", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_limits",
        sa.Column("bucket_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_hash"),
    )
    op.create_index("ix_auth_limits_expiry", "auth_limits", ["expires_at"])
    op.create_table(
        "auth_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("req_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_events_user_created", "auth_events", ["usr_id", "created_at"])


def downgrade() -> None:
    op.drop_table("auth_events")
    op.drop_table("auth_limits")
    op.drop_table("auth_sessions")
    op.drop_table("auth_verify")
    op.drop_table("auth_accounts")
