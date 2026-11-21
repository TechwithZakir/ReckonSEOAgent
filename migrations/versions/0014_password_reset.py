"""Add one-time password recovery tokens.

Revision ID: 0014_password_reset
Revises: 0013_platform_admin
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_password_reset"
down_revision: str | None = "0013_platform_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_reset",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_reset_expiry", "auth_reset", ["expires_at"])
    op.create_index("ix_auth_reset_user", "auth_reset", ["usr_id"])


def downgrade() -> None:
    op.drop_table("auth_reset")
