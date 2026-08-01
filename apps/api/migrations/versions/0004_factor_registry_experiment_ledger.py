"""Adopt the factor registry and append-only experiment ledger schema.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31
"""

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ADOPTED_TABLES = (
    "factor_research_plans",
    "factor_definitions",
    "factor_candidate_validations",
    "factor_experiments",
    "factor_experiment_events",
)

ADOPTED_INDEXES = (
    "idx_factor_research_plans_market",
    "idx_factor_definitions_formula",
    "idx_factor_candidate_validations_definition",
    "idx_factor_experiments_plan",
    "idx_factor_experiment_events_experiment",
)

ADOPTED_COLUMNS = (
    ("factor_experiments", "proposal_json"),
    ("factor_experiment_events", "event_sequence"),
    ("factor_experiments", "estimated_compute_units"),
    ("factor_experiments", "candidate_validation_id"),
)


def upgrade() -> None:
    # env.py runs store._init() before migrations, so the exact application
    # schema already exists when this adoption revision is stamped.
    pass


def downgrade() -> None:
    # Experiment history is append-only evidence. Database rollback restores a
    # verified backup instead of deleting registry or experiment records.
    pass
