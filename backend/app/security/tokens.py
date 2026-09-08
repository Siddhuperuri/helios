"""Tokens: access, refresh, verification and password reset.

Four token types, three different designs, each chosen for what it has to survive.

**Access tokens** are short-lived signed JWTs. They are not stored anywhere, which is the
point: verifying one is a signature check with no round-trip, so the hot path of every
authenticated request costs nothing. The price is that an access token cannot be revoked
before it expires, which is why it expires in fifteen minutes.

**Refresh tokens** are opaque random strings. They *are* stored — as a SHA-256 digest,
never in the clear — because they must be revocable: on logout, on password reset, and on
detecting that one has been stolen. They rotate on every use.

**Verification and reset tokens** are opaque random strings with a stored expiry. They are
single-use: consuming one deletes it. They keep a tombstone past their expiry so that an
expired link can be reported as ``token_expired`` rather than as an indistinguishable
"invalid", which is the difference between a user pressing "send me another one" and a user
concluding the product is broken.

Refresh-token reuse detection
-----------------------------
Rotation alone means a stolen token stops working once the real user refreshes. It does not
tell anybody that the theft happened. So a rotated-away token is remembered for the rest of
its original lifetime, and presenting one is treated as evidence of compromise: every
refresh token for that account is revoked, forcing a fresh sign-in on every device. That is
disruptive, and it is meant to be — the alternative is leaving an attacker holding a valid
session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt

from app.config import get_settings
from app.infra import redis_client

logger = logging.getLogger(__name__)

TokenPurpose = Literal["verify_email", "password_reset"]

# Opaque tokens carry 32 bytes of entropy. That is well past the point where guessing is
# the weakest link, and still short enough to survive being pasted out of an email client.
_TOKEN_BYTES = 32

# How long after expiry a consumed-or-expired token is remembered, purely so the API can
# say *why* a link no longer works. Nothing is authorised on the strength of a tombstone.
_TOMBSTONE_GRACE = timedelta(days=7)


class TokenError(Exception):
    """A token could not be accepted.

    ``code`` is the machine-readable reason the frontend switches on:
    ``token_expired``, ``token_used``, ``token_invalid``, ``token_revoked``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(token: str) -> str:
    """SHA-256 of a token.

    Storing the digest rather than the token means a dump of Redis does not hand over
    working credentials. A plain hash is right here, unlike for passwords: the input is 32
    bytes of uniform randomness, so there is nothing for a brute-force to be faster at.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------------
# Access tokens
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    email: str
    is_verified: bool
    expires_at: datetime
    jti: str


def create_access_token(
    *, user_id: str | uuid.UUID, email: str, is_verified: bool
) -> tuple[str, int]:
    """Mint an access token. Returns ``(token, seconds_until_expiry)``.

    ``is_verified`` rides in the claims so that a route can gate on it without a database
    read. It is a snapshot: someone who verifies their address mid-session carries a stale
    ``false`` until their next refresh, at most fifteen minutes later. That is acceptable
    for what verification gates — nothing in the calculator — and the verification endpoint
    returns a fresh token so the common path does not wait at all.
    """
    auth = get_settings().auth
    issued = _now()
    expires = issued + timedelta(minutes=auth.access_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "verified": bool(is_verified),
        "typ": "access",
        "iss": auth.jwt_issuer,
        "aud": auth.jwt_audience,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, auth.jwt_secret, algorithm=auth.jwt_algorithm)
    return token, int((expires - issued).total_seconds())


def decode_access_token(token: str) -> AccessClaims:
    """Verify an access token and return its claims, or raise :class:`TokenError`."""
    auth = get_settings().auth
    try:
        payload = jwt.decode(
            token,
            auth.jwt_secret,
            # Pinned rather than read from the token's own header: accepting whatever the
            # header claims is how algorithm-confusion attacks work.
            algorithms=[auth.jwt_algorithm],
            audience=auth.jwt_audience,
            issuer=auth.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token_expired", "That session has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token_invalid", "That sign-in token is not valid.") from exc

    if payload.get("typ") != "access":
        # A refresh token presented as a bearer token, for instance.
        raise TokenError("token_invalid", "That is not an access token.")

    return AccessClaims(
        user_id=str(payload["sub"]),
        email=str(payload.get("email", "")),
        is_verified=bool(payload.get("verified", False)),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        jti=str(payload.get("jti", "")),
    )


# --------------------------------------------------------------------------------------
# Refresh tokens
# --------------------------------------------------------------------------------------

def _refresh_key(digest: str) -> str:
    return redis_client.key("refresh", digest)


def _refresh_index_key(user_id: str) -> str:
    """The set of live refresh digests for one account, so all of them can be revoked."""
    return redis_client.key("refresh-index", user_id)


def _refresh_used_key(digest: str) -> str:
    return redis_client.key("refresh-used", digest)


def issue_refresh_token(user_id: str | uuid.UUID) -> tuple[str, int]:
    """Mint a refresh token. Returns ``(token, seconds_until_expiry)``."""
    auth = get_settings().auth
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    digest = _digest(token)
    ttl = int(timedelta(days=auth.refresh_ttl_days).total_seconds())
    record = {"user_id": str(user_id), "issued_at": _now().isoformat()}

    client = redis_client.get_client()
    pipeline = client.pipeline(transaction=False)
    pipeline.set(_refresh_key(digest), json.dumps(record), ex=ttl)
    pipeline.sadd(_refresh_index_key(str(user_id)), digest)
    # The index must not outlive the longest-lived token in it, or a dormant account
    # accumulates a set that never expires.
    pipeline.expire(_refresh_index_key(str(user_id)), ttl + 86_400)
    pipeline.execute()
    return token, ttl


def rotate_refresh_token(token: str) -> tuple[str, str, int]:
    """Exchange a refresh token for a new one.

    Returns ``(user_id, new_token, ttl)``. Raises :class:`TokenError` if the token is
    unknown, already rotated away, or belongs to a revoked family.
    """
    digest = _digest(token)
    client = redis_client.get_client()

    raw = client.get(_refresh_key(digest))
    if raw is None:
        # Was this token one we previously rotated away? If so it should be dead, and
        # somebody is holding a copy of it — which means it leaked.
        replayed = client.get(_refresh_used_key(digest))
        if replayed:
            logger.warning(
                "Refresh token reuse detected for user %s; revoking every session for "
                "that account.",
                replayed,
            )
            revoke_all_refresh_tokens(replayed)
            raise TokenError(
                "token_revoked",
                "For your security, every session for this account has been signed out. "
                "Sign in again.",
            )
        raise TokenError("token_invalid", "Your session has ended. Sign in again.")

    record = json.loads(raw)
    user_id = str(record["user_id"])

    remaining = client.ttl(_refresh_key(digest))
    remaining = int(remaining) if remaining and remaining > 0 else 60

    new_token, ttl = issue_refresh_token(user_id)

    pipeline = client.pipeline(transaction=False)
    pipeline.delete(_refresh_key(digest))
    pipeline.srem(_refresh_index_key(user_id), digest)
    # Remember the rotated-away token for what would have been the rest of its life. After
    # that it is indistinguishable from any other invalid string, which is fine — an
    # attacker replaying a token a month after it was issued learns nothing either way.
    pipeline.set(_refresh_used_key(digest), user_id, ex=remaining)
    pipeline.execute()

    return user_id, new_token, ttl


def read_refresh_token(token: str) -> str | None:
    """The owner of a refresh token without consuming it, or ``None``."""
    try:
        raw = redis_client.get_client().get(_refresh_key(_digest(token)))
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    try:
        return str(json.loads(raw)["user_id"])
    except (json.JSONDecodeError, KeyError):
        return None


def revoke_refresh_token(token: str) -> bool:
    """Revoke one refresh token. Used by logout, which should end one device's session."""
    digest = _digest(token)
    client = redis_client.get_client()
    raw = client.get(_refresh_key(digest))
    if raw is None:
        return False
    try:
        user_id = str(json.loads(raw)["user_id"])
    except (json.JSONDecodeError, KeyError):
        user_id = ""
    pipeline = client.pipeline(transaction=False)
    pipeline.delete(_refresh_key(digest))
    if user_id:
        pipeline.srem(_refresh_index_key(user_id), digest)
    pipeline.execute()
    return True


def revoke_all_refresh_tokens(user_id: str | uuid.UUID) -> int:
    """Revoke every refresh token for an account. Returns how many were live.

    Called on password reset and on password change, which is the whole reason the index
    set exists. Changing a password because you think somebody has your session is
    pointless if their session survives it.
    """
    user_id = str(user_id)
    client = redis_client.get_client()
    index = _refresh_index_key(user_id)
    try:
        digests = list(client.smembers(index))
    except Exception:  # noqa: BLE001
        return 0
    if not digests:
        client.delete(index)
        return 0

    pipeline = client.pipeline(transaction=False)
    for digest in digests:
        pipeline.delete(_refresh_key(digest))
    pipeline.delete(index)
    pipeline.execute()
    logger.info("Revoked %d refresh token(s) for user %s", len(digests), user_id)
    return len(digests)


def count_refresh_tokens(user_id: str | uuid.UUID) -> int:
    try:
        return int(redis_client.get_client().scard(_refresh_index_key(str(user_id))))
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------------------------------
# Single-use email tokens
# --------------------------------------------------------------------------------------

def _purpose_key(purpose: TokenPurpose, digest: str) -> str:
    return redis_client.key("token", purpose, digest)


def _purpose_index_key(purpose: TokenPurpose, user_id: str) -> str:
    """Digests of one account's outstanding tokens of one kind.

    Costs one extra SADD per issue and makes "invalidate every reset link for this
    account" a real operation rather than an aspiration.
    """
    return redis_client.key("token-index", purpose, user_id)


def issue_email_token(
    purpose: TokenPurpose, user_id: str | uuid.UUID, *, ttl_hours: int | None = None
) -> tuple[str, datetime]:
    """Mint a single-use token for verification or password reset.

    Returns ``(token, expires_at)``. Only the digest is stored; the token itself exists
    only in the email that carries it.
    """
    auth = get_settings().auth
    if ttl_hours is None:
        ttl_hours = (
            auth.verification_ttl_hours
            if purpose == "verify_email"
            else auth.password_reset_ttl_hours
        )

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    digest = _digest(token)
    expires_at = _now() + timedelta(hours=ttl_hours)
    record = {
        "user_id": str(user_id),
        "expires_at": expires_at.isoformat(),
        "purpose": purpose,
    }
    # Held past its own expiry so that the reason a link stopped working is still knowable.
    storage_ttl = int((timedelta(hours=ttl_hours) + _TOMBSTONE_GRACE).total_seconds())
    index = _purpose_index_key(purpose, str(user_id))

    pipeline = redis_client.get_client().pipeline(transaction=False)
    pipeline.set(_purpose_key(purpose, digest), json.dumps(record), ex=storage_ttl)
    pipeline.sadd(index, digest)
    pipeline.expire(index, storage_ttl + 3600)
    pipeline.execute()
    return token, expires_at


def consume_email_token(purpose: TokenPurpose, token: str) -> str:
    """Validate and spend a token, returning the user id it was issued for.

    Raises :class:`TokenError` with ``token_expired`` for a link that has timed out and
    ``token_invalid`` for one that was never issued, was already used, or is malformed.
    """
    if not token or len(token) > 512:
        raise TokenError("token_invalid", "That link is not valid.")

    digest = _digest(token)
    key = _purpose_key(purpose, digest)
    client = redis_client.get_client()

    raw = client.get(key)
    if raw is None:
        raise TokenError(
            "token_invalid",
            "That link is not valid. It may already have been used, or a newer one may "
            "have replaced it.",
        )

    try:
        record = json.loads(raw)
        expires_at = datetime.fromisoformat(record["expires_at"])
        user_id = str(record["user_id"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        client.delete(key)
        raise TokenError("token_invalid", "That link is not valid.") from exc

    if _now() > expires_at:
        client.delete(key)
        client.srem(_purpose_index_key(purpose, user_id), digest)
        raise TokenError(
            "token_expired",
            "That link has expired. Request a new one and it will be sent straight away.",
        )

    # Single use: spend it before returning, so two simultaneous clicks cannot both win.
    # DELETE returns the number of keys removed, so exactly one caller sees a 1.
    if not client.delete(key):
        raise TokenError("token_invalid", "That link has already been used.")
    client.srem(_purpose_index_key(purpose, user_id), digest)

    return user_id


def revoke_email_tokens_for_user(purpose: TokenPurpose, user_id: str | uuid.UUID) -> int:
    """Invalidate every outstanding token of one kind for one account.

    Called after a password reset succeeds, so that a second reset link sitting in the
    same inbox — or in an attacker's copy of it — cannot be used to set the password
    again afterwards.
    """
    user_id = str(user_id)
    index = _purpose_index_key(purpose, user_id)
    client = redis_client.get_client()
    try:
        digests = list(client.smembers(index))
    except Exception:  # noqa: BLE001
        return 0
    if not digests:
        client.delete(index)
        return 0
    pipeline = client.pipeline(transaction=False)
    for digest in digests:
        pipeline.delete(_purpose_key(purpose, digest))
    pipeline.delete(index)
    pipeline.execute()
    return len(digests)


def describe() -> dict[str, Any]:
    """Token policy, for the health payload and for the frontend's session timing."""
    auth = get_settings().auth
    return {
        "access_ttl_minutes": auth.access_ttl_minutes,
        "refresh_ttl_days": auth.refresh_ttl_days,
        "verification_ttl_hours": auth.verification_ttl_hours,
        "password_reset_ttl_hours": auth.password_reset_ttl_hours,
    }
