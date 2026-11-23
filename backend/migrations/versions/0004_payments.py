"""Add SQLite payment persistence.

Revision ID: 0004_payments
Revises: 0003_invoice_number_reservations
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_payments"
down_revision = "0003_invoice_number_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoiceId", sa.String(), nullable=False),
        sa.Column("clientId", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("receivedAt", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("proof_fileName", sa.String(), nullable=True),
        sa.Column("proof_mimeType", sa.String(), nullable=True),
        sa.Column("proof_sizeBytes", sa.Integer(), nullable=True),
        sa.Column("proof_uploadedAt", sa.String(), nullable=True),
        sa.Column("proof_attachmentReference", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoiceId", "clientId"],
            ["invoices.id", "invoices.clientId"],
            name="fk_payments_invoice_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["clientId"],
            ["clients.id"],
            name="fk_payments_clientId_clients",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proof_attachmentReference",
            name="uq_payments_proof_attachmentReference",
        ),
    )
    op.create_index("ix_payments_invoiceId", "payments", ["invoiceId"])
    op.create_index("ix_payments_clientId", "payments", ["clientId"])
    op.create_index("ix_payments_receivedAt", "payments", ["receivedAt"])


def downgrade() -> None:
    op.drop_index("ix_payments_receivedAt", table_name="payments")
    op.drop_index("ix_payments_clientId", table_name="payments")
    op.drop_index("ix_payments_invoiceId", table_name="payments")
    op.drop_table("payments")
