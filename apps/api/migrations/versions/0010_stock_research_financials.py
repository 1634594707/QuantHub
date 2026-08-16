"""Add point-in-time stock financial and valuation storage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-16
"""

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite/PostgreSQL schema.
    pass


def downgrade() -> None:
    # Research evidence is immutable audit data and is intentionally retained.
    pass
