"""Persist bounded robots.txt sitemap discovery.

Revision ID: 0007_robots_sitemap_discovery
Revises: 0006_homepage_indexability
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_robots_sitemap_discovery"
down_revision: str | None = "0006_homepage_indexability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column("robots_status_code", sa.Integer(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("sitemap_urls", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("sitemap_declaration_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("sitemap_rejected_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("sitemap_discovery_truncated", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        "ck_site_crawl_runs_sitemap_declarations",
        "site_crawl_runs",
        "sitemap_declaration_count IS NULL OR sitemap_declaration_count >= 0",
    )
    op.create_check_constraint(
        "ck_site_crawl_runs_sitemap_rejected",
        "site_crawl_runs",
        "sitemap_rejected_count IS NULL OR sitemap_rejected_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_site_crawl_runs_sitemap_rejected",
        "site_crawl_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_site_crawl_runs_sitemap_declarations",
        "site_crawl_runs",
        type_="check",
    )
    op.drop_column("site_crawl_runs", "sitemap_discovery_truncated")
    op.drop_column("site_crawl_runs", "sitemap_rejected_count")
    op.drop_column("site_crawl_runs", "sitemap_declaration_count")
    op.drop_column("site_crawl_runs", "sitemap_urls")
    op.drop_column("site_crawl_runs", "robots_status_code")
