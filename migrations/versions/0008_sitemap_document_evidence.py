"""Persist bounded sitemap document evidence.

Revision ID: 0008_sitemap_document_evidence
Revises: 0007_robots_sitemap_discovery
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_sitemap_document_evidence"
down_revision: str | None = "0007_robots_sitemap_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column(
            "sitemap_evidence",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("site_crawl_runs", "sitemap_evidence")
