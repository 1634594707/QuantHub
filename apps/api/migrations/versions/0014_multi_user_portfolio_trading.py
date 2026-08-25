"""Add ownership to portfolio/holdings/signals/ledger/simulation orders.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25
"""

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite/PostgreSQL schema via _ensure_column.
    pass


def downgrade() -> None:
    # User ownership is audit-relevant and intentionally retained.
    pass
