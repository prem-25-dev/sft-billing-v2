"""Add Invoice and InvoiceItem core tables.

Revision ID: 0002_invoice_core
Revises: 0001_sqlite
Create Date: 2026-10-07

Payments, activities, and invoice-number reservations intentionally remain
outside this revision.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_invoice_core"
down_revision = "0001_sqlite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("number", sa.String(), nullable=False),
        sa.Column("clientId", sa.String(), nullable=False),
        sa.Column("issueDate", sa.String(), nullable=False),
        sa.Column("dueDate", sa.String(), nullable=False),
        sa.Column("cgstRate", sa.Float(), nullable=False),
        sa.Column("sgstRate", sa.Float(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("roundOff", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("terms", sa.String(), nullable=True),
        sa.Column("supplierCode", sa.String(), nullable=True),
        sa.Column("poNumber", sa.String(), nullable=True),
        sa.Column("poDate", sa.String(), nullable=True),
        sa.Column("transporter", sa.String(), nullable=True),
        sa.Column("isDraft", sa.Boolean(), nullable=False),
        sa.Column("sentAt", sa.String(), nullable=True),
        sa.Column("viewedAt", sa.String(), nullable=True),
        sa.Column("paidAt", sa.String(), nullable=True),
        sa.Column("cancelledAt", sa.String(), nullable=True),
        sa.Column("billedAt", sa.String(), nullable=True),
        sa.Column("customerNameSnapshot", sa.String(), nullable=True),
        sa.Column("customerAddressSnapshot", sa.String(), nullable=True),
        sa.Column("customerPhoneSnapshot", sa.String(), nullable=True),
        sa.Column("customerEmailSnapshot", sa.String(), nullable=True),
        sa.Column("customerGstinSnapshot", sa.String(), nullable=True),
        sa.Column("customerPanSnapshot", sa.String(), nullable=True),
        sa.Column("businessNameSnapshot", sa.String(), nullable=True),
        sa.Column("businessLogoUrlSnapshot", sa.String(), nullable=True),
        sa.Column("businessAddressSnapshot", sa.String(), nullable=True),
        sa.Column("businessPhoneSnapshot", sa.String(), nullable=True),
        sa.Column("businessEmailSnapshot", sa.String(), nullable=True),
        sa.Column("businessGstinSnapshot", sa.String(), nullable=True),
        sa.Column("businessPanSnapshot", sa.String(), nullable=True),
        sa.Column("businessBankAccountHolderSnapshot", sa.String(), nullable=True),
        sa.Column("businessBankNameSnapshot", sa.String(), nullable=True),
        sa.Column("businessBankBranchSnapshot", sa.String(), nullable=True),
        sa.Column("businessBankAccountNumberSnapshot", sa.String(), nullable=True),
        sa.Column("businessBankIfscSnapshot", sa.String(), nullable=True),
        sa.Column("businessDeclarationSnapshot", sa.String(), nullable=True),
        sa.Column("authorizedSignatureReferenceSnapshot", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["clientId"],
            ["clients.id"],
            name="fk_invoices_clientId_clients",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "clientId", name="uq_invoices_id_clientId"),
        sa.UniqueConstraint("number", name="uq_invoices_number"),
    )
    op.create_index("ix_invoices_clientId", "invoices", ["clientId"])
    op.create_index("ix_invoices_issueDate", "invoices", ["issueDate"])
    op.create_index("ix_invoices_dueDate", "invoices", ["dueDate"])
    op.create_table(
        "invoice_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("invoiceId", sa.String(), nullable=False),
        sa.Column("productId", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("hsnCode", sa.String(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unitPrice", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoiceId"],
            ["invoices.id"],
            name="fk_invoice_items_invoiceId_invoices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_items_invoiceId", "invoice_items", ["invoiceId"])


def downgrade() -> None:
    op.drop_index("ix_invoice_items_invoiceId", table_name="invoice_items")
    op.drop_table("invoice_items")
    op.drop_index("ix_invoices_dueDate", table_name="invoices")
    op.drop_index("ix_invoices_issueDate", table_name="invoices")
    op.drop_index("ix_invoices_clientId", table_name="invoices")
    op.drop_table("invoices")
