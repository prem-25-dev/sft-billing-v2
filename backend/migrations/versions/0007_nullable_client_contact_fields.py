"""Allow blank historical client contact fields.

Revision ID: 0007_nullable_client_contact_fields
Revises: 0001_sqlite
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_nullable_client_contact_fields"
down_revision = "0001_sqlite"
branch_labels = ("client_contact_nullable",)
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clients", recreate="always") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(),
            nullable=True,
        )
        batch_op.alter_column(
            "phone",
            existing_type=sa.String(),
            nullable=True,
        )
        batch_op.alter_column(
            "pan",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        has_null_contacts = connection.exec_driver_sql(
            "SELECT 1 FROM clients "
            "WHERE email IS NULL OR phone IS NULL OR pan IS NULL LIMIT 1"
        ).first()
        if has_null_contacts:
            raise RuntimeError(
                "Cannot restore required Client contact fields while NULL values exist."
            )

    with op.batch_alter_table("clients", recreate="always") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "phone",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "pan",
            existing_type=sa.String(),
            nullable=False,
        )
