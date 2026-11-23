"""Add the SQLite Business Profile singleton.

Revision ID: 0006_business_profile
Revises: 0005_activities
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_business_profile"
down_revision = "0005_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("logoUrl", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("gstin", sa.String(), nullable=True),
        sa.Column("pan", sa.String(), nullable=True),
        sa.Column("bank_accountHolder", sa.String(), nullable=True),
        sa.Column("bank_bankName", sa.String(), nullable=True),
        sa.Column("bank_branch", sa.String(), nullable=True),
        sa.Column("bank_accountNumber", sa.String(), nullable=True),
        sa.Column("bank_ifsc", sa.String(), nullable=True),
        sa.Column("declaration", sa.String(), nullable=True),
        sa.Column("authorizedSignatory", sa.String(), nullable=True),
        sa.Column("defaultGst_cgstRate", sa.Float(), nullable=True),
        sa.Column("defaultGst_sgstRate", sa.Float(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_business_profile_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("business_profile")
