"""Add user alert rules and trigger history.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("frequency_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("quiet_start", sa.Text(), nullable=True),
        sa.Column("quiet_end", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_checked_at", sa.Float(), nullable=True),
        sa.Column("last_triggered_at", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        if_not_exists=True,
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("related_type", sa.Text(), nullable=True),
        sa.Column("related_id", sa.Text(), nullable=True),
        sa.Column("delivery_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("triggered_at", sa.Float(), nullable=False),
        sa.Column("acknowledged_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("alert_events", if_exists=True)
    op.drop_table("alert_rules", if_exists=True)
