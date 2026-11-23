"""Add recovery_attempts table for rate limiting.

Revision ID: 0012_recovery_attempts
Revises: 0011_auth
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_recovery_attempts"
down_revision = "0011_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("createdAt", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recovery_attempts_username", "recovery_attempts", ["username"])
    op.create_index("ix_recovery_attempts_created_at", "recovery_attempts", ["createdAt"])


def downgrade() -> None:
    op.drop_index("ix_recovery_attempts_created_at", table_name="recovery_attempts")
    op.drop_index("ix_recovery_attempts_username", table_name="recovery_attempts")
    op.drop_table("recovery_attempts")