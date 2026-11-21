"""Add bounded multi-page crawl evidence.

Revision ID: 0017_multi_page_crawl_evidence
Revises: 0016_model_endpoint
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_multi_page_crawl_evidence"
down_revision: str | None = "0016_model_endpoint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column("internal_urls", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("page_evidence", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("site_crawl_runs", "page_evidence")
    op.drop_column("site_crawl_runs", "internal_urls")
