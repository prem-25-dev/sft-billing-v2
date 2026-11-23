"""Add permanently consumed invoice-number reservations.

Revision ID: 0003_invoice_number_reservations
Revises: 0002_invoice_core
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_invoice_number_reservations"
down_revision = "0002_invoice_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_number_reservations",
        sa.Column("number", sa.String(), nullable=False),
        sa.Column("financialYear", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("reservedFor", sa.String(), nullable=True),
        sa.Column("reservedAt", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("number"),
        sa.UniqueConstraint(
            "financialYear",
            "sequence",
            name="uq_invoice_reservations_year_sequence",
        ),
        sa.UniqueConstraint("reservedFor", name="uq_invoice_reservations_reservedFor"),
    )
    op.create_index(
        "ix_invoice_number_reservations_financialYear",
        "invoice_number_reservations",
        ["financialYear"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_number_reservations_financialYear",
        table_name="invoice_number_reservations",
    )
    op.drop_table("invoice_number_reservations")
