"""Add SQLite activity/audit-event persistence.

Revision ID: 0005_activities
Revises: 0004_payments
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_activities"
down_revision = "0004_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("occurredAt", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("clientId", sa.String(), nullable=True),
        sa.Column("invoiceId", sa.String(), nullable=True),
        sa.Column("paymentId", sa.String(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["clientId"],
            ["clients.id"],
            name="fk_activities_clientId_clients",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invoiceId"],
            ["invoices.id"],
            name="fk_activities_invoiceId_invoices",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paymentId"],
            ["payments.id"],
            name="fk_activities_paymentId_payments",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activities_occurredAt", "activities", ["occurredAt"])
    op.create_index("ix_activities_clientId", "activities", ["clientId"])
    op.create_index("ix_activities_invoiceId", "activities", ["invoiceId"])
    op.create_index("ix_activities_paymentId", "activities", ["paymentId"])


def downgrade() -> None:
    op.drop_index("ix_activities_paymentId", table_name="activities")
    op.drop_index("ix_activities_invoiceId", table_name="activities")
    op.drop_index("ix_activities_clientId", table_name="activities")
    op.drop_index("ix_activities_occurredAt", table_name="activities")
    op.drop_table("activities")
