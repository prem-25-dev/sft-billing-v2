"""Add notification model for user notifications.

Revision ID: 0010_notifications
Revises: 0009_products
Create Date: 2026-11-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_notifications"
down_revision = "0009_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("referenceId", sa.String(), nullable=True),
        sa.Column("referenceType", sa.String(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("occurredAt", sa.String(), nullable=False),
        sa.Column("readAt", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_occurredAt", "notifications", ["occurredAt"])
    op.create_index("ix_notifications_category", "notifications", ["category"])
    op.create_index("ix_notifications_read", "notifications", ["read"])
    op.create_index("ix_notifications_category_read", "notifications", ["category", "read"])


def downgrade() -> None:
    op.drop_index("ix_notifications_category_read", table_name="notifications")
    op.drop_index("ix_notifications_read", table_name="notifications")
    op.drop_index("ix_notifications_category", table_name="notifications")
    op.drop_index("ix_notifications_occurredAt", table_name="notifications")
    op.drop_table("notifications")