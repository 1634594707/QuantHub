"""Adopt the complete application schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-27
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "automation_audit_logs",
    "automation_runs",
    "automation_job_overrides",
    "simulation_executions",
    "simulation_orders",
    "analysis_tasks",
    "research_evidence",
    "research_runs",
    "audit_logs",
    "api_tokens",
    "role_permissions",
    "user_roles",
    "permissions",
    "roles",
    "users",
    "data_source_incidents",
    "ledger_corrections",
    "ledger_benchmarks",
    "ledger_positions",
    "ledger_cash",
    "ledger_trades",
    "backtest_runs",
    "experiments",
    "strategy_versions",
    "strategy_definitions",
    "instruments",
    "signals",
    "app_meta",
    "watchlist",
    "holdings",
    "portfolio_allocs",
    "strategy_runs",
    "strategy_presets",
)


def upgrade() -> None:
    # env.py initializes the exact application schema before stamping this revision.
    pass


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
