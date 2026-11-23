"""Add a mobile number to users (used for account recovery).

Revision ID: 0013_user_mobile
Revises: 0012_recovery_attempts
Create Date: 2026-11-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_user_mobile"
down_revision = "0012_recovery_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("mobile", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("mobile")
