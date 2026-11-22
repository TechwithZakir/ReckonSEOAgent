"""Add scoped, revocable Claude plugin tokens.

Revision ID: 0022_plugin_tokens
Revises: 0021_seo_action_lifecycle
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022_plugin_tokens"
down_revision: str | None = "0021_seo_action_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugin_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "usr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plugin_tokens_org", "plugin_tokens", ["org_id", "created_at"])
    # No row-level security: like auth_sessions, the table is read before an organization
    # context exists, by token digest. Every management query filters on org_id explicitly.


def downgrade() -> None:
    op.drop_index("ix_plugin_tokens_org", table_name="plugin_tokens")
    op.drop_table("plugin_tokens")
