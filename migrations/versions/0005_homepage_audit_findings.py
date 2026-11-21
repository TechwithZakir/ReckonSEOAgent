"""Persist deterministic homepage audit findings.

Revision ID: 0005_homepage_audit_findings
Revises: 0004_crawl_page_metadata
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_homepage_audit_findings"
down_revision: str | None = "0004_crawl_page_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column("audit_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("audit_findings", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("site_crawl_runs", "audit_findings")
    op.drop_column("site_crawl_runs", "audit_version")
