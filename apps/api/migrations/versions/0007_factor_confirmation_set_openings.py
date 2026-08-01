"""Adopt irreversible locked confirmation-set opening audit records.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31
"""

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

ADOPTED_TABLES = ("factor_confirmation_set_openings",)
ADOPTED_INDEXES = ("idx_factor_confirmation_openings_experiment",)


def upgrade() -> None:
    # store._init() owns the exact cross-database schema before Alembic stamps it.
    pass


def downgrade() -> None:
    # Opening the locked confirmation set is an irreversible research event.
    pass
