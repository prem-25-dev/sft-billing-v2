"""Create the SQLite clients table.

Revision ID: 0001_sqlite
Revises:
Create Date: 2026-10-07

This initial revision is deliberately limited to Clients. Other billing
domains remain Excel-backed and will receive separate revisions when
migrated.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_sqlite"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contactName", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("billingAddress", sa.String(), nullable=False),
        sa.Column("gstin", sa.String(), nullable=False),
        sa.Column("pan", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("clients")
