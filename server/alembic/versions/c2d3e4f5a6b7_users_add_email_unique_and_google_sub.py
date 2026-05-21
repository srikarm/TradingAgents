"""users: add google_sub, make github_id nullable, unique partial index on email

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make github_id nullable — Google-only users won't have one.
    # Use batch mode for SQLite compatibility (SQLite can't ALTER COLUMN directly).
    with op.batch_alter_table("users") as batch:
        batch.alter_column("github_id", existing_type=sa.String(64), nullable=True)

    # Add google_sub (nullable, indexed, unique-where-not-null).
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.create_index("ix_users_google_sub", "users", ["google_sub"])
    op.create_index(
        "ix_users_google_sub_unique",
        "users",
        ["google_sub"],
        unique=True,
        postgresql_where=sa.text("google_sub IS NOT NULL"),
    )

    # email is already a nullable column — add a unique partial index.
    op.create_index(
        "ix_users_email_unique",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    """
    WARNING: This downgrade is one-way safe ONLY on a database that has
    never had a Google-only user (i.e., a user row where github_id IS NULL).
    The ALTER COLUMN github_id NOT NULL step below will fail on PostgreSQL
    if any such row exists.

    If you need to roll back after Google sign-ins have happened, first
    decide on a strategy for the NULL-github_id rows (delete them, copy
    google_sub into github_id as a sentinel, or skip the NOT NULL restore).
    """
    op.drop_index("ix_users_email_unique", "users")
    op.drop_index("ix_users_google_sub_unique", "users")
    op.drop_index("ix_users_google_sub", "users")
    op.drop_column("users", "google_sub")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("github_id", existing_type=sa.String(64), nullable=False)
