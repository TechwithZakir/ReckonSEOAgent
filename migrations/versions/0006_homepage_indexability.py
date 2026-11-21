"""Persist homepage indexability signals.

Revision ID: 0006_homepage_indexability
Revises: 0005_homepage_audit_findings
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_homepage_indexability"
down_revision: str | None = "0005_homepage_audit_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_crawl_runs",
        sa.Column("meta_robots_noindex", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("x_robots_noindex", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "site_crawl_runs",
        sa.Column("canonical_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_site_crawl_runs_canonical_count",
        "site_crawl_runs",
        "canonical_count IS NULL OR canonical_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_site_crawl_runs_canonical_count",
        "site_crawl_runs",
        type_="check",
    )
    op.drop_column("site_crawl_runs", "canonical_count")
    op.drop_column("site_crawl_runs", "canonical_url")
    op.drop_column("site_crawl_runs", "x_robots_noindex")
    op.drop_column("site_crawl_runs", "meta_robots_noindex")
