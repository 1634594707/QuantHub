"""Add watchlist ownership for multi-user research workflows.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-16
"""

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite/PostgreSQL schema.
    pass


def downgrade() -> None:
    # User ownership is audit-relevant and intentionally retained.
    pass
