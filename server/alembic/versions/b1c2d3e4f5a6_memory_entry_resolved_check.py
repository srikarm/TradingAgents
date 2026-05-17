"""memory_entry_resolved_check

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18 00:00:00.000000

Backfills any pre-existing (status=RESOLVED, raw_return IS NULL) rows by
demoting status to PENDING, then adds the
ck_memory_entry_resolved_has_raw_return CHECK constraint so the bad state
becomes unrepresentable. See spec §5.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Backfill: existing RESOLVED rows with NULL raw_return are by definition
    # parse-failures that snuck through. Demote to PENDING so the constraint
    # can be applied. Re-sync from disk recovers proper RESOLVED status
    # once the disk markdown is corrected.
    op.execute(
        "UPDATE memory_entries "
        "SET status = 'PENDING' "
        "WHERE status = 'RESOLVED' AND raw_return IS NULL"
    )
    with op.batch_alter_table("memory_entries") as batch:
        batch.create_check_constraint(
            "ck_memory_entry_resolved_has_raw_return",
            "status != 'RESOLVED' OR raw_return IS NOT NULL",
        )


def downgrade() -> None:
    """Downgrade schema.

    No reverse backfill — once a row is demoted to PENDING in upgrade(),
    downgrade cannot infer the original raw_return value.
    """
    with op.batch_alter_table("memory_entries") as batch:
        batch.drop_constraint(
            "ck_memory_entry_resolved_has_raw_return", type_="check"
        )
