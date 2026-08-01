"""Adopt structured AI search governance and failure feedback.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-31
"""

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

ADOPTED_TABLES = ("factor_ai_search_rounds",)
ADOPTED_INDEXES = ("idx_factor_ai_search_rounds_plan",)
ADOPTED_COLUMNS = (("factor_experiment_events", "failure_code"),)


def upgrade() -> None:
    # store._init() owns the exact cross-database schema before Alembic stamps it.
    pass


def downgrade() -> None:
    # Search rounds and failure feedback are immutable research evidence.
    pass
