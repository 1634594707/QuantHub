"""Adopt the factor research lifecycle schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31
"""

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ADOPTED_TABLES = (
    "factor_universes",
    "factor_universe_members",
    "factor_research_jobs",
    "research_incidents",
)

ADOPTED_COLUMNS = (
    ("experiments", "research_run_id"),
    ("research_runs", "tags_json"),
    ("research_runs", "archived_at"),
)

ADOPTED_INDEXES = (
    "idx_factor_universe_market",
    "idx_factor_members_universe",
    "idx_factor_research_jobs_enabled",
    "idx_research_incidents_status",
    "idx_research_archived",
)


def upgrade() -> None:
    # env.py runs store._init() before migrations, so the exact application
    # schema already exists when this adoption revision is stamped.
    pass


def downgrade() -> None:
    # QuantHub database rollback uses a verified pre-upgrade backup. Removing
    # these objects in place would discard research history and incident data.
    pass
