"""Add the Products Master and inventory movement ledger.

Revision ID: 0009_products
Revises: 0008_merge_client_nullable_branch
Create Date: 2026-10-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_products"
down_revision = "0008_merge_client_nullable_branch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("hsnCode", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("defaultUnitPrice", sa.Integer(), nullable=False),
        sa.Column("defaultGstRate", sa.Float(), nullable=False),
        sa.Column("weightMilli", sa.Integer(), nullable=True),
        sa.Column("weightUnit", sa.String(), nullable=True),
        sa.Column("purchaseCost", sa.Integer(), nullable=True),
        sa.Column("lowStockThresholdMilli", sa.Integer(), nullable=True),
        sa.Column("stockOnHandMilli", sa.Integer(), nullable=True),
        sa.Column("isActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("createdAt", sa.String(), nullable=False),
        sa.Column("updatedAt", sa.String(), nullable=False),
        sa.CheckConstraint("type IN ('product', 'service')", name="ck_products_type"),
        sa.CheckConstraint(
            "defaultUnitPrice >= 0",
            name="ck_products_defaultUnitPrice",
        ),
        sa.CheckConstraint(
            "defaultGstRate >= 0 AND defaultGstRate <= 1",
            name="ck_products_defaultGstRate",
        ),
        sa.CheckConstraint(
            "weightMilli IS NULL OR weightMilli >= 0",
            name="ck_products_weightMilli",
        ),
        sa.CheckConstraint(
            "(weightMilli IS NULL AND weightUnit IS NULL) OR "
            "(weightMilli IS NOT NULL AND weightUnit IS NOT NULL)",
            name="ck_products_weight_pair",
        ),
        sa.CheckConstraint(
            "weightUnit IS NULL OR weightUnit IN ('g', 'kg', 'ml', 'L')",
            name="ck_products_weightUnit",
        ),
        sa.CheckConstraint(
            "purchaseCost IS NULL OR purchaseCost >= 0",
            name="ck_products_purchaseCost",
        ),
        sa.CheckConstraint(
            "lowStockThresholdMilli IS NULL OR lowStockThresholdMilli >= 0",
            name="ck_products_lowStockThresholdMilli",
        ),
        sa.CheckConstraint(
            "stockOnHandMilli IS NULL OR stockOnHandMilli >= 0",
            name="ck_products_stockOnHandMilli",
        ),
        sa.CheckConstraint(
            "type = 'product' OR lowStockThresholdMilli IS NULL",
            name="ck_products_service_no_stock_threshold",
        ),
        sa.CheckConstraint(
            "type = 'product' OR stockOnHandMilli IS NULL",
            name="ck_products_service_no_stock",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_products_code"),
    )
    op.create_index(
        "ix_products_isActive_type_name",
        "products",
        ["isActive", "type", "name"],
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("productId", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("quantityChangeMilli", sa.Integer(), nullable=False),
        sa.Column("resultingBalanceMilli", sa.Integer(), nullable=False),
        sa.Column("occurredAt", sa.String(), nullable=False),
        sa.Column("idempotencyKey", sa.String(), nullable=False),
        sa.Column("invoiceId", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.CheckConstraint(
            "type IN ('opening', 'receipt', 'issue', 'adjustment')",
            name="ck_inventory_movements_type",
        ),
        sa.CheckConstraint(
            "(type = 'opening' AND quantityChangeMilli >= 0) OR "
            "(type = 'receipt' AND quantityChangeMilli > 0) OR "
            "(type = 'issue' AND quantityChangeMilli < 0) OR "
            "(type = 'adjustment' AND quantityChangeMilli != 0)",
            name="ck_inventory_movements_quantity_change",
        ),
        sa.CheckConstraint(
            "resultingBalanceMilli >= 0",
            name="ck_inventory_movements_resulting_balance",
        ),
        sa.CheckConstraint(
            "type != 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_inventory_movements_adjustment_reason",
        ),
        sa.ForeignKeyConstraint(
            ["productId"],
            ["products.id"],
            name="fk_inventory_movements_productId_products",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invoiceId"],
            ["invoices.id"],
            name="fk_inventory_movements_invoiceId_invoices",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotencyKey",
            name="uq_inventory_movements_idempotencyKey",
        ),
    )
    op.create_index(
        "uq_inventory_movements_opening_product",
        "inventory_movements",
        ["productId"],
        unique=True,
        sqlite_where=sa.text("type = 'opening'"),
    )
    op.create_index(
        "uq_inventory_movements_invoice_issue",
        "inventory_movements",
        ["invoiceId", "productId"],
        unique=True,
        sqlite_where=sa.text("invoiceId IS NOT NULL AND type = 'issue'"),
    )
    op.create_index(
        "ix_inventory_movements_product_occurredAt",
        "inventory_movements",
        ["productId", "occurredAt"],
    )
    op.create_index(
        "ix_inventory_movements_invoiceId",
        "inventory_movements",
        ["invoiceId"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_invoiceId", table_name="inventory_movements")
    op.drop_index(
        "ix_inventory_movements_product_occurredAt",
        table_name="inventory_movements",
    )
    op.drop_index(
        "uq_inventory_movements_invoice_issue",
        table_name="inventory_movements",
    )
    op.drop_index(
        "uq_inventory_movements_opening_product",
        table_name="inventory_movements",
    )
    op.drop_table("inventory_movements")
    op.drop_index("ix_products_isActive_type_name", table_name="products")
    op.drop_table("products")
