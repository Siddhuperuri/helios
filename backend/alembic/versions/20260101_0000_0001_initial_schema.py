"""Initial schema: users, oauth_accounts, estimates, experiments.

Revision ID: 0001_initial
Revises:
Created: initial

This is the first migration in the project's history, so there is no older release for it
to stay compatible with. Every migration after it must be: see the note in
alembic/script.py.mako.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID, JSONDocument

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "oauth_accounts",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=320), nullable=True),
        sa.Column("provider_username", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_accounts"),
        # An account's OAuth links are meaningless without the account.
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_oauth_accounts_user", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider", "provider_account_id", name="uq_oauth_provider_account"
        ),
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])
    op.create_index(
        "ix_oauth_accounts_provider_account",
        "oauth_accounts",
        ["provider", "provider_account_id"],
    )

    op.create_table(
        "estimates",
        sa.Column("estimate_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", GUID(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("payload", JSONDocument(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_label", sa.String(length=255), nullable=True),
        sa.Column("user_type", sa.String(length=64), nullable=True),
        sa.Column("capacity_kwp", sa.Float(), nullable=True),
        sa.Column("annual_kwh", sa.Float(), nullable=True),
        sa.Column("payback_years", sa.Float(), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("estimate_id", name="pk_estimates"),
        # SET NULL, not CASCADE: an estimate may already have been shared by its opaque
        # link, and closing an account is not consent to break that link for whoever holds
        # it. The estimate reverts to anonymous.
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_estimates_owner", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_estimates_created_at", "estimates", ["created_at"])
    op.create_index("ix_estimates_owner_updated", "estimates", ["owner_id", "updated_at"])

    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("model_key", sa.String(length=64), nullable=False),
        sa.Column("model_display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("target", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("location_label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("latitude", sa.Float(), nullable=False, server_default="0"),
        sa.Column("longitude", sa.Float(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("period_end", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("n_train", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_test", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", JSONDocument(), nullable=False),
        sa.Column("cv_summary", JSONDocument(), nullable=False),
        sa.Column("skill_scores", JSONDocument(), nullable=False),
        sa.Column("interval_metrics", JSONDocument(), nullable=False),
        sa.Column("manifest", JSONDocument(), nullable=False),
        sa.Column("warnings", JSONDocument(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("experiment_id", name="pk_experiments"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_experiments_owner", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_experiments_created_at", "experiments", ["created_at"])
    op.create_index("ix_experiments_model_key", "experiments", ["model_key"])
    op.create_index("ix_experiments_owner_created", "experiments", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_table("experiments")
    op.drop_table("estimates")
    op.drop_table("oauth_accounts")
    op.drop_table("users")
