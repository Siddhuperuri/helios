"""The schema.

Four tables. Three decisions in here are worth stating rather than leaving to be inferred
from the DDL.

**Estimates keep their opaque token as the primary key.** Everywhere else a UUID surrogate
is the right default, but an estimate already has a cryptographically random public
identifier that appears in a URL a user may have sent to their installer. Introducing a
second identity for the same row would buy nothing and create a way for the two to
disagree.

**Deleting an account must not delete estimates.** ``users → estimates`` and
``users → experiments`` are ``ON DELETE SET NULL``. An estimate can already have been
shared by its link; closing an account is not consent to break that link for whoever holds
it. The row simply reverts to being anonymous, which is what it would have been had the
person never signed in. ``users → oauth_accounts`` is ``ON DELETE CASCADE``, because a
credential linkage to a user who no longer exists is meaningless.

**Summary columns are denormalised out of the payload.** The dashboard lists estimates by
location, size, yield and payback. Reading a multi-megabyte JSON document per row to render
a list would be indefensible, so those six values are written alongside the payload when it
is saved. The payload remains the source of truth; the columns are a projection of it,
rewritten whenever it is.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID, JSONDocument


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An account.

    ``hashed_password`` is nullable, and that nullability is load-bearing: somebody who
    signed up with Google has no password, and inventing an unusable placeholder hash for
    them would make "does this account have a password?" a question about the shape of a
    string. The account-settings screen and the last-authentication-method check both read
    this column directly.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    # Stored normalised to lower case. Addresses are compared case-insensitively, and a
    # unique index over a mixed-case column would happily accept two of the same person.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def has_password(self) -> bool:
        return bool(self.hashed_password)

    def to_dict(self) -> dict[str, Any]:
        """The public view of an account. Never includes the hash."""
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "has_password": self.has_password,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "providers": sorted(account.provider for account in self.oauth_accounts),
        }


class OAuthAccount(Base):
    """A third-party identity linked to an account.

    The unique constraint is on ``(provider, provider_account_id)`` rather than on the
    email the provider reported. A provider's subject identifier is stable and belongs to
    exactly one account there; an email address is neither of those things, and treating
    it as an identity is how OAuth account-takeover happens.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),
        Index("ix_oauth_accounts_provider_account", "provider", "provider_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the provider said this identity's address and name were at link time. Kept for
    # the account-settings screen only; the address in `users` is the authoritative one.
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    provider_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="oauth_accounts")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_account_id": self.provider_account_id,
            "provider_email": self.provider_email,
            "provider_username": self.provider_username,
            "linked_at": self.created_at.isoformat() if self.created_at else None,
        }


class Estimate(Base):
    """A saved consumer estimate.

    ``owner_id`` is nullable and that is the whole ownership model: null means the
    estimate was produced anonymously and is reachable only by its opaque link, exactly as
    before accounts existed. Non-null means it also appears in one person's dashboard. The
    link keeps working either way.
    """

    __tablename__ = "estimates"
    __table_args__ = (
        # The dashboard query: this owner's estimates, newest first.
        Index("ix_estimates_owner_updated", "owner_id", "updated_at"),
    )

    estimate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # No standalone index: the composite below has owner_id as its leading column, which
    # serves both the dashboard query and the ON DELETE SET NULL lookup.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # Projection of the payload, for listing without reading it. See the module docstring.
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capacity_kwp: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    payback_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Experiment(Base):
    """A recorded training run from the analysis console."""

    __tablename__ = "experiments"
    __table_args__ = (Index("ix_experiments_owner_created", "owner_id", "created_at"),)

    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    model_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    location_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    latitude: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    period_start: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    period_end: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    n_train: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_test: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    metrics: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False, default=dict)
    cv_summary: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False, default=dict)
    skill_scores: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False, default=dict)
    interval_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONDocument, nullable=False, default=dict
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSONDocument, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
