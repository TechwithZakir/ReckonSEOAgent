"""Persist deterministic homepage SEO metadata.

Revision ID: 0004_crawl_page_metadata
Revises: 0003_site_crawl_runs
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_crawl_page_metadata"
down_revision: str | None = "0003_site_crawl_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column("meta_desc", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("h1_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_site_crawl_runs_h1_count",
        "site_crawl_runs",
        "h1_count IS NULL OR h1_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_site_crawl_runs_h1_count",
        "site_crawl_runs",
        type_="check",
    )
    op.drop_column("site_crawl_runs", "h1_count")
    op.drop_column("site_crawl_runs", "meta_desc")
