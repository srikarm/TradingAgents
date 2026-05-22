"""add_monitor_columns

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "monitor_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("briefing_time_local", sa.String(5), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("briefing_tz", sa.String(64), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column(
            "triggered_by",
            sa.String(16),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "triggered_by")
    op.drop_column("users", "briefing_tz")
    op.drop_column("users", "briefing_time_local")
    op.drop_column("users", "monitor_enabled")
