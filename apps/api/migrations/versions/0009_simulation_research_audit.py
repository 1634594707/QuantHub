"""Persist research and execution audit metadata for paper orders.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-01
"""

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite schema and adds this column idempotently.
    pass


def downgrade() -> None:
    # Audit evidence is append-only and is intentionally retained.
    pass
