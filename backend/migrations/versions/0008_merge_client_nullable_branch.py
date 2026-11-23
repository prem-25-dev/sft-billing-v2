"""Merge the Client nullability and existing domain migration branches.

Revision ID: 0008_merge_client_nullable_branch
Revises: 0006_business_profile, 0007_nullable_client_contact_fields
Create Date: 2026-10-08
"""

from __future__ import annotations

revision = "0008_merge_client_nullable_branch"
down_revision = ("0006_business_profile", "0007_nullable_client_contact_fields")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
