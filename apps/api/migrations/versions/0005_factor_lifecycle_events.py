"""Adopt the append-only factor lifecycle event ledger.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ADOPTED_TABLES = ("factor_lifecycle_events",)
ADOPTED_INDEXES = ("idx_factor_lifecycle_definition_market",)


def upgrade() -> None:
    # store._init() owns the exact cross-database schema before Alembic stamps it.
    pass


def downgrade() -> None:
    # Lifecycle evidence is append-only and is restored from a verified backup.
    pass
