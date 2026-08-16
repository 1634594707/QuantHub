"""Add company events, macro events, relationships, and transmissions.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite/PostgreSQL schema.
    pass


def downgrade() -> None:
    # Point-in-time research evidence is immutable and intentionally retained.
    pass
