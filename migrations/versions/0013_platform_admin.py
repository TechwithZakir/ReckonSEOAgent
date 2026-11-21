"""Add a singleton initial platform administrator.

Revision ID: 0013_platform_admin
Revises: 0012_native_auth
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_platform_admin"
down_revision: str | None = "0012_native_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_admin",
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("usr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("slot = 1", name="ck_platform_admin_slot"),
        sa.ForeignKeyConstraint(["usr_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("slot"),
        sa.UniqueConstraint("usr_id"),
    )


def downgrade() -> None:
    op.drop_table("platform_admin")
