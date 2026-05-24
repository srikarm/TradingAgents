"""add_notifications

Wave 5.4 — notification opt-in columns on users + monitor_batches +
notifications (delivery ledger) tables.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-24
"""
import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Opt-in prefs on users. server_default false/'none' backfills existing
    # rows so no current user is surprise-notified.
    op.add_column(
        "users",
        sa.Column(
            "notify_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_channel",
            sa.String(16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_threshold",
            sa.String(32),
            nullable=False,
            server_default="BUY,SELL",
        ),
    )

    op.create_table(
        "monitor_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.String(10), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "trade_date", name="uq_monitor_batch_user_date"
        ),
    )
    op.create_index(
        "ix_monitor_batches_user_id", "monitor_batches", ["user_id"]
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "trade_date",
            "channel",
            name="uq_notification_user_date_channel",
        ),
    )
    op.create_index(
        "ix_notifications_user_id", "notifications", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_monitor_batches_user_id", table_name="monitor_batches")
    op.drop_table("monitor_batches")
    op.drop_column("users", "notify_threshold")
    op.drop_column("users", "notify_channel")
    op.drop_column("users", "notify_enabled")
