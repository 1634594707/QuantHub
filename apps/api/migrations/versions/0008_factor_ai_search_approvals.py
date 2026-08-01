"""Adopt immutable researcher approvals for AI search rounds.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-31
"""

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

ADOPTED_COLUMNS = (("factor_ai_search_rounds", "approval_json"),)


def upgrade() -> None:
    # store._init() owns the exact cross-database schema before Alembic stamps it.
    pass


def downgrade() -> None:
    # Researcher approval is immutable audit evidence and is intentionally retained.
    pass
