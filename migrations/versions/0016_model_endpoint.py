"""Add an optional organization model API base URL.

Revision ID: 0016_model_endpoint
Revises: 0015_org_management
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0016_model_endpoint"
down_revision: str | None = "0015_org_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("org_model_settings", sa.Column("endpoint_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("org_model_settings", "endpoint_url")
