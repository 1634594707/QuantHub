"""Add multi-user ownership and research preferences.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-16
"""

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store._init() owns the portable SQLite/PostgreSQL schema.
    pass


def downgrade() -> None:
    # Ownership and user preferences are audit-relevant and intentionally retained.
    pass
