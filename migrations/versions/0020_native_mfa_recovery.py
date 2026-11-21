"""Add one-time native-account MFA recovery codes.

Revision ID: 0020_native_mfa_recovery
Revises: 0019_crawl_schedules
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020_native_mfa_recovery"
down_revision: str | None = "0019_crawl_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_mfa_recovery",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "usr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_auth_mfa_recovery_user",
        "auth_mfa_recovery",
        ["usr_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_mfa_recovery_user",
        table_name="auth_mfa_recovery",
    )
    op.drop_table("auth_mfa_recovery")
