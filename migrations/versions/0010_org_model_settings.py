"""Add encrypted per-organization model settings.

Revision ID: 0010_org_model_settings
Revises: 0009_model_usage
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_org_model_settings"
down_revision: str | None = "0009_model_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_model_settings",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("key_cipher", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('openai', 'anthropic')", name="ck_org_model_settings_provider"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.execute("ALTER TABLE org_model_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_model_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY org_model_settings_scope ON org_model_settings
        USING (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_model_settings_scope ON org_model_settings")
    op.execute("ALTER TABLE org_model_settings DISABLE ROW LEVEL SECURITY")
    op.drop_table("org_model_settings")
