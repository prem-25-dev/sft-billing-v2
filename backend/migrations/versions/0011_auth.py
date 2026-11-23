"""Add authentication tables: users, sessions, password_reset_tokens.

Revision ID: 0011_auth
Revises: 0010_notifications
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_auth"
down_revision = "0010_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("recoveryKeyHash", sa.String(), nullable=True),
        sa.Column("isAdmin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("createdAt", sa.String(), nullable=False),
        sa.Column("lastLoginAt", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("userId", sa.String(), nullable=False),
        sa.Column("tokenHash", sa.String(), nullable=False),
        sa.Column("expiresAt", sa.String(), nullable=False),
        sa.Column("createdAt", sa.String(), nullable=False),
        sa.Column("lastUsedAt", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["users.id"],
            name="fk_sessions_userId_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["userId"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expiresAt"])
    op.create_index("ix_sessions_token_hash", "sessions", ["tokenHash"], unique=True)

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("userId", sa.String(), nullable=False),
        sa.Column("tokenHash", sa.String(), nullable=False),
        sa.Column("expiresAt", sa.String(), nullable=False),
        sa.Column("usedAt", sa.String(), nullable=True),
        sa.Column("createdAt", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["users.id"],
            name="fk_password_reset_tokens_userId_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["userId"])
    op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["tokenHash"], unique=True)
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expiresAt"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")