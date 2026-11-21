"""Add native-account TOTP enrollment and MFA challenges.

Revision ID: 0018_native_mfa
Revises: 0017_multi_page_crawl_evidence
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_native_mfa"
down_revision: str | None = "0017_multi_page_crawl_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_accounts",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "auth_accounts",
        sa.Column("mfa_secret_cipher", sa.LargeBinary(), nullable=True),
    )
    op.execute("ALTER TABLE auth_accounts ALTER COLUMN mfa_enabled DROP DEFAULT")
    op.create_table(
        "auth_mfa_challenges",
        sa.Column("challenge_hash", sa.String(64), primary_key=True),
        sa.Column(
            "usr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_auth_mfa_challenges_expiry",
        "auth_mfa_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_mfa_challenges_expiry",
        table_name="auth_mfa_challenges",
    )
    op.drop_table("auth_mfa_challenges")
    op.drop_column("auth_accounts", "mfa_secret_cipher")
    op.drop_column("auth_accounts", "mfa_enabled")
