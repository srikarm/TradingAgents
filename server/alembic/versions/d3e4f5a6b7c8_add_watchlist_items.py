"""add_watchlist_items

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )
    op.create_index(
        "ix_watchlist_user_added",
        "watchlist_items",
        ["user_id", sa.text("added_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_user_added", table_name="watchlist_items")
    op.drop_table("watchlist_items")
