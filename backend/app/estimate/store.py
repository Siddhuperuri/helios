"""Durable storage for estimates, so a result outlives the process that made it.

The research surface keeps analyses in an in-process LRU of twelve, which is right for a
workbench: the artefacts are large, and losing them costs a re-run. It is wrong for a
consumer product. Somebody who spent four minutes answering questions about their farm
should be able to close the tab, come back tomorrow, and still find their result — and
should be able to send the link to an installer (§35).

Estimates were one JSON file each on the backend's own disk. They are now rows in
PostgreSQL, for a reason that has nothing to do with the file format: with more than one
backend replica behind a load balancer, an estimate written by replica 1 simply did not
exist for replicas 2 and 3. The interface below is unchanged so that the routes and the
engine did not have to be.

Two properties are preserved exactly, because the product depends on them:

*No account is required to create one* (§35: calculate first, save later). An anonymous
estimate has a null owner and behaves as it always did.

*The identifier in the URL is what grants access to it.* That remains a deliberate,
stated trade-off: a link is a bearer token here. Anyone holding it can read the estimate.
Estimates hold a location, an electricity bill and a system design, which is not nothing,
so the identifier is generated from a cryptographic source rather than a counter or a hash
of the inputs, and it is long enough not to be guessable.

What ownership adds is narrower than it sounds. It does not gate reading — that would
break every link already sent. It gates *writing*: once an estimate belongs to somebody,
only they can rename, edit or delete it. An estimate with no owner is still writable by
whoever holds the link, exactly as before.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import Estimate

logger = logging.getLogger(__name__)

# 16 bytes of entropy via token_urlsafe. Long enough that guessing is not a practical
# attack, short enough to sit in a URL a person might read aloud.
_ID_BYTES = 16


def new_id() -> str:
    return secrets.token_urlsafe(_ID_BYTES)


def _valid_id(estimate_id: str) -> bool:
    """Reject anything that is not shaped like one of our identifiers.

    This used to defend a path join. There is no path any more, but the check is worth
    keeping: it turns a malformed link into a clean 404 without a database round-trip, and
    it stops an oversized identifier from being sent to the server at all.
    """
    if not estimate_id or len(estimate_id) > 64:
        return False
    return all(ch.isalnum() or ch in {"-", "_"} for ch in estimate_id)


def _iso(value: datetime | None) -> str:
    """Timestamps are rendered exactly as the file store rendered them.

    Seconds precision, UTC, ISO-8601. The frontend parses these and existing saved
    payloads carry them, so the format is part of the contract rather than a detail.
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StoredEstimate:
    estimate_id: str
    created_at: str
    updated_at: str
    label: str
    payload: dict[str, Any]
    owner_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimate_id": self.estimate_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "label": self.label,
            **self.payload,
        }

    def summary(self) -> dict[str, Any]:
        """The compact form used for a list of saved estimates."""
        generation = self.payload.get("generation") or {}
        system = self.payload.get("system") or {}
        location = self.payload.get("location") or {}
        economics = self.payload.get("economics") or {}
        return {
            "estimate_id": self.estimate_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "label": self.label,
            "location_label": location.get("label"),
            "user_type": self.payload.get("user_type"),
            "capacity_kwp": system.get("capacity_kwp"),
            "annual_kwh": generation.get("annual_kwh"),
            "payback_years": economics.get("payback_years"),
            "confidence": (self.payload.get("uncertainty") or {}).get("confidence"),
        }


def _from_row(row: Estimate) -> StoredEstimate:
    return StoredEstimate(
        estimate_id=row.estimate_id,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        label=row.label or "",
        payload=row.payload or {},
        owner_id=str(row.owner_id) if row.owner_id else None,
    )


def _default_label(payload: dict[str, Any]) -> str:
    location = (payload.get("location") or {}).get("label") or "Unnamed location"
    system = payload.get("system") or {}
    capacity = system.get("capacity_kwp")
    return f"{location} — {capacity:g} kW" if capacity else str(location)


def _project(row: Estimate, payload: dict[str, Any]) -> None:
    """Copy the listable figures out of the payload onto the row.

    Kept in one function so the projection cannot drift between a first save and a later
    edit: both call this, so a listing never shows a figure the payload has moved past.
    """
    generation = payload.get("generation") or {}
    system = payload.get("system") or {}
    location = payload.get("location") or {}
    economics = payload.get("economics") or {}
    uncertainty = payload.get("uncertainty") or {}

    def _number(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None

    row.location_label = (location.get("label") or None) and str(location["label"])[:255]
    row.user_type = (payload.get("user_type") or None) and str(payload["user_type"])[:64]
    row.capacity_kwp = _number(system.get("capacity_kwp"))
    row.annual_kwh = _number(generation.get("annual_kwh"))
    row.payback_years = _number(economics.get("payback_years"))
    row.confidence = (uncertainty.get("confidence") or None) and str(uncertainty["confidence"])[:32]


# --------------------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------------------

def save(
    payload: dict[str, Any],
    *,
    label: str | None = None,
    owner_id: str | uuid.UUID | None = None,
) -> StoredEstimate:
    """Persist a new estimate and return it with its identifier.

    ``owner_id`` is the only new argument, and it is optional. Omit it and the estimate is
    anonymous, which is what the calculator does for a signed-out visitor.
    """
    estimate_id = new_id()
    now = datetime.now(timezone.utc)
    resolved_label = (label or payload.get("label") or _default_label(payload)) or ""

    with session_scope() as session:
        row = Estimate(
            estimate_id=estimate_id,
            owner_id=_as_uuid(owner_id),
            label=str(resolved_label)[:200],
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        _project(row, payload)
        session.add(row)
        session.flush()
        record = _from_row(row)

    logger.info(
        "Saved estimate %s (%s)", estimate_id, "owned" if owner_id else "anonymous"
    )
    return record


def rename(estimate_id: str, label: str) -> StoredEstimate | None:
    if not _valid_id(estimate_id):
        return None
    with session_scope() as session:
        row = session.get(Estimate, estimate_id)
        if row is None:
            return None
        cleaned = label.strip()
        if cleaned:
            row.label = cleaned[:200]
        row.updated_at = datetime.now(timezone.utc)
        session.flush()
        return _from_row(row)


def update_payload(estimate_id: str, payload: dict[str, Any]) -> StoredEstimate | None:
    """Replace the stored result, keeping identity, ownership and creation time."""
    if not _valid_id(estimate_id):
        return None
    with session_scope() as session:
        row = session.get(Estimate, estimate_id)
        if row is None:
            return None
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)
        _project(row, payload)
        session.flush()
        return _from_row(row)


def claim(estimate_id: str, owner_id: str | uuid.UUID) -> StoredEstimate | None:
    """Attach an existing anonymous estimate to an account.

    For the case the interview creates naturally: somebody runs an estimate, likes it, and
    only then signs in. An estimate that already has an owner is never reassigned — that
    would let anyone holding a link take an estimate off the person it belongs to.
    """
    if not _valid_id(estimate_id):
        return None
    with session_scope() as session:
        row = session.get(Estimate, estimate_id)
        if row is None or row.owner_id is not None:
            return None
        row.owner_id = _as_uuid(owner_id)
        row.updated_at = datetime.now(timezone.utc)
        session.flush()
        return _from_row(row)


def delete(estimate_id: str) -> bool:
    if not _valid_id(estimate_id):
        return False
    with session_scope() as session:
        row = session.get(Estimate, estimate_id)
        if row is None:
            return False
        session.delete(row)
        return True


# --------------------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------------------

def get(estimate_id: str) -> StoredEstimate | None:
    if not _valid_id(estimate_id):
        # A malformed identifier is a link that does not resolve, not a server fault. The
        # caller renders "we could not find that estimate", which is both true and useful.
        logger.info("Rejected malformed estimate identifier")
        return None
    with session_scope() as session:
        row = session.get(Estimate, estimate_id)
        return _from_row(row) if row is not None else None


def owner_of(estimate_id: str) -> str | None:
    """The owner's id, or ``None`` for an anonymous estimate or one that is not there."""
    if not _valid_id(estimate_id):
        return None
    with session_scope() as session:
        owner = session.execute(
            select(Estimate.owner_id).where(Estimate.estimate_id == estimate_id)
        ).scalar_one_or_none()
        return str(owner) if owner else None


def list_for_owner(owner_id: str | uuid.UUID, limit: int = 50) -> list[dict[str, Any]]:
    """One person's estimates, most recently updated first.

    This replaced a function called ``recent()`` that listed every estimate the server
    held. That was honest for a single-user deployment and stated as such, but it cannot
    survive accounts: it would show one user another user's location and electricity bill.
    There is deliberately no way to ask this module for estimates that are not yours.
    """
    resolved = _as_uuid(owner_id)
    if resolved is None:
        return []
    bounded = max(1, min(int(limit), 200))
    with session_scope() as session:
        rows = (
            session.execute(
                select(Estimate)
                .where(Estimate.owner_id == resolved)
                .order_by(Estimate.updated_at.desc())
                .limit(bounded)
            )
            .scalars()
            .all()
        )
        return [_summary_from_row(row) for row in rows]


def count_for_owner(owner_id: str | uuid.UUID) -> int:
    resolved = _as_uuid(owner_id)
    if resolved is None:
        return 0
    from sqlalchemy import func

    with session_scope() as session:
        return int(
            session.execute(
                select(func.count()).select_from(Estimate).where(Estimate.owner_id == resolved)
            ).scalar_one()
        )


def _summary_from_row(row: Estimate) -> dict[str, Any]:
    """Build a listing entry from the projected columns, not from the payload.

    The payload of a single estimate can run to megabytes. Rendering a list of fifty by
    deserialising fifty of those would make the dashboard the slowest page in the product.
    """
    return {
        "estimate_id": row.estimate_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "label": row.label or "",
        "location_label": row.location_label,
        "user_type": row.user_type,
        "capacity_kwp": row.capacity_kwp,
        "annual_kwh": row.annual_kwh,
        "payback_years": row.payback_years,
        "confidence": row.confidence,
    }


# --------------------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------------------

def prune(max_age_days: int | None = None) -> int:
    """Delete *anonymous* estimates older than a cut-off. Returns how many went.

    The retention sweep exists because an anonymous estimate has nobody to tidy up after
    it. An owned one does: it belongs to somebody who can see it in their dashboard and
    delete it when they are finished with it. Expiring a saved estimate out from under its
    owner would be data loss dressed up as housekeeping, so ownership is now part of the
    predicate.
    """
    days = max_age_days if max_age_days is not None else get_settings().store.estimate_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as session:
        # `session.execute` is typed as returning the base `Result`, which has no
        # `rowcount`; a DELETE always returns a `CursorResult`, which does. Narrowing it
        # here is more honest than reaching through an ignore comment.
        result = cast(CursorResult[Any], session.execute(
            sa_delete(Estimate).where(
                Estimate.owner_id.is_(None), Estimate.created_at < cutoff
            )
        ))
        return int(result.rowcount or 0)


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


# --------------------------------------------------------------------------------------
# Session-bound variants
# --------------------------------------------------------------------------------------
#
# The functions above open their own transaction, which is what the estimate routes want:
# each is a single self-contained write. Auth routes sometimes need to do several things
# in one transaction, so the two operations they use are also available against a caller's
# session.

def list_for_owner_in(session: Session, owner_id: uuid.UUID, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(Estimate)
            .where(Estimate.owner_id == owner_id)
            .order_by(Estimate.updated_at.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        .scalars()
        .all()
    )
    return [_summary_from_row(row) for row in rows]
