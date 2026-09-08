"""Account operations.

Everything here takes a session and returns a model or raises :class:`AuthError`. No route
handling, no HTTP, no cookies — those live in ``routes.py``, so the rules below can be
tested without a client.

Two rules in this module are security decisions rather than implementation details, and
both are the kind that get quietly relaxed for convenience:

**Registration never reveals whether an address is already in use.** The response is the
same either way; the person who already has an account gets an email saying so instead of a
new one. An endpoint that answers "that email is taken" is an account-enumeration oracle,
and it is on the internet with no authentication in front of it.

**OAuth never merges accounts on a matching email.** If somebody signs in with Google using
an address that already has a password account, they are told to sign in and link it from
their settings. Automatic merging means anyone who can get a provider to assert an address
— including via a provider that does not verify addresses — inherits the account behind it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OAuthAccount, User
from app.security import passwords, tokens

logger = logging.getLogger(__name__)

MAX_EMAIL_LENGTH = 320


class AuthError(Exception):
    """An account operation was refused.

    ``code`` is machine-readable and stable; ``message`` is written for a person and is
    what the interface shows.
    """

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class RegistrationOutcome:
    """What actually happened, so the route can decide what email to send.

    The route's *response* is identical in both cases — see the module docstring — but it
    still has to send the right message, and that decision needs this.
    """

    user: User | None
    created: bool
    existing_account: bool


def normalise_email(email: str) -> str:
    """Trim and lower-case.

    The local part of an address is technically case-sensitive; in practice no provider
    that matters treats it that way, and treating it that way here would let one person
    hold two accounts on what they consider one address, then be unable to explain why
    their password does not work.
    """
    return (email or "").strip().lower()


def validate_email_shape(email: str) -> None:
    if not email or len(email) > MAX_EMAIL_LENGTH:
        raise AuthError("invalid_email", "That does not look like an email address.", status=422)
    try:
        from email_validator import validate_email

        # deliverability=False: no DNS lookup. A registration request should not block on
        # a resolver, and an MX check does not establish that a mailbox exists anyway —
        # sending the verification mail is what does that.
        validate_email(email, check_deliverability=False)
    except ImportError:  # pragma: no cover - email-validator is a hard requirement
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise AuthError(
                "invalid_email", "That does not look like an email address.", status=422
            ) from None
    except Exception as exc:  # noqa: BLE001 - EmailNotValidError and its subclasses
        raise AuthError(
            "invalid_email", "That does not look like an email address.", status=422
        ) from exc


# --------------------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------------------

def get_user(session: Session, user_id: str | uuid.UUID) -> User | None:
    try:
        resolved = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return session.get(User, resolved)


def get_user_by_email(session: Session, email: str) -> User | None:
    normalised = normalise_email(email)
    if not normalised:
        return None
    return session.execute(
        select(User).where(User.email == normalised)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------------------
# Password accounts
# --------------------------------------------------------------------------------------

def register(session: Session, email: str, password: str) -> RegistrationOutcome:
    """Create an account, or report that the address already has one.

    Never raises for a duplicate. The caller must produce an identical response either
    way; only the email that follows differs.
    """
    normalised = normalise_email(email)
    validate_email_shape(normalised)

    problem = passwords.password_problem(password)
    if problem:
        raise AuthError("weak_password", problem, status=422)

    existing = get_user_by_email(session, normalised)
    if existing is not None:
        logger.info("Registration attempted for an address that already has an account")
        return RegistrationOutcome(user=existing, created=False, existing_account=True)

    user = User(
        email=normalised,
        hashed_password=passwords.hash_password(password),
        is_active=True,
        is_verified=False,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        # Two simultaneous registrations for the same address. The unique index is the
        # authority, not the SELECT above, which is why this is caught rather than assumed
        # away.
        session.rollback()
        existing = get_user_by_email(session, normalised)
        return RegistrationOutcome(user=existing, created=False, existing_account=True)

    logger.info("Created account %s", user.id)
    return RegistrationOutcome(user=user, created=True, existing_account=False)


def authenticate(session: Session, email: str, password: str) -> User:
    """Check credentials and return the account, or raise.

    One error for every failure mode — wrong password, no such account, deactivated — so
    the response cannot be used to learn which addresses are registered. The password is
    verified even when there is no account, so the timing cannot be either.
    """
    user = get_user_by_email(session, email)
    stored_hash = user.hashed_password if user else None

    if not passwords.verify_password(password, stored_hash) or user is None:
        raise AuthError(
            "invalid_credentials",
            "That email address and password do not match an account.",
            status=401,
        )

    if not user.is_active:
        raise AuthError(
            "account_disabled",
            "That account has been deactivated. Contact support if you think this is wrong.",
            status=403,
        )

    # The one moment the plaintext is available to upgrade an outdated hash.
    if passwords.needs_rehash(user.hashed_password):
        user.hashed_password = passwords.hash_password(password)
        logger.info("Upgraded password hash parameters for %s", user.id)

    user.last_login_at = datetime.now(timezone.utc)
    return user


def set_password(session: Session, user: User, new_password: str, *, revoke_sessions: bool = True) -> None:
    """Set a new password and, by default, end every existing session.

    Revocation is the point of the operation, not a side effect. Somebody changing their
    password because they think it is compromised gains nothing if the attacker's refresh
    token keeps working for another thirty days.
    """
    problem = passwords.password_problem(new_password)
    if problem:
        raise AuthError("weak_password", problem, status=422)

    user.hashed_password = passwords.hash_password(new_password)
    session.flush()

    if revoke_sessions:
        revoked = tokens.revoke_all_refresh_tokens(user.id)
        logger.info("Password changed for %s; revoked %d session(s)", user.id, revoked)


def mark_verified(session: Session, user: User) -> User:
    user.is_verified = True
    session.flush()
    return user


# --------------------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------------------

def get_oauth_account(
    session: Session, provider: str, provider_account_id: str
) -> OAuthAccount | None:
    return session.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_account_id == str(provider_account_id),
        )
    ).scalar_one_or_none()


def sign_in_with_provider(
    session: Session,
    *,
    provider: str,
    provider_account_id: str,
    email: str | None,
    display_name: str | None = None,
    username: str | None = None,
) -> tuple[User, bool]:
    """Sign in or sign up through a provider. Returns ``(user, created)``.

    Three cases, and the third is the one that matters:

    1. This provider identity is already linked — sign that account in.
    2. Nothing matches — create an account. It is verified immediately, because the
       provider has already established that the person controls the address.
    3. The address belongs to an existing account this identity is *not* linked to —
       refuse, and tell them to sign in and link it deliberately. See the module docstring.
    """
    linked = get_oauth_account(session, provider, provider_account_id)
    if linked is not None:
        user = linked.user
        if not user.is_active:
            raise AuthError(
                "account_disabled",
                "That account has been deactivated.",
                status=403,
            )
        # Refresh what the provider currently says, so account settings do not show a
        # stale address forever.
        linked.provider_email = (email or linked.provider_email or None)
        linked.provider_username = username or linked.provider_username
        user.last_login_at = datetime.now(timezone.utc)
        session.flush()
        return user, False

    normalised = normalise_email(email or "")
    if normalised:
        existing = get_user_by_email(session, normalised)
        if existing is not None:
            raise AuthError(
                "link_required",
                (
                    f"There is already a Helios account for {normalised}. Sign in to it "
                    f"first, then connect {provider.title()} from your account settings. "
                    f"We do not link accounts automatically, because an address on its own "
                    f"is not proof of ownership."
                ),
                status=409,
            )

    if not normalised:
        raise AuthError(
            "email_required",
            (
                f"{provider.title()} did not share an email address, so we cannot create "
                f"an account. Make your address public or verified with {provider.title()}, "
                f"or sign up with an email and password instead."
            ),
            status=422,
        )

    user = User(
        email=normalised,
        hashed_password=None,
        display_name=display_name,
        is_active=True,
        # The provider has verified the address. Asking the person to verify it again
        # would be asking them to prove something already proved.
        is_verified=True,
        last_login_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.flush()

    session.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_account_id=str(provider_account_id),
            provider_email=normalised,
            provider_username=username,
        )
    )
    session.flush()
    logger.info("Created account %s via %s", user.id, provider)
    return user, True


def link_provider(
    session: Session,
    user: User,
    *,
    provider: str,
    provider_account_id: str,
    email: str | None,
    username: str | None = None,
) -> OAuthAccount:
    """Attach a provider identity to the account making the request."""
    existing = get_oauth_account(session, provider, provider_account_id)
    if existing is not None:
        if existing.user_id == user.id:
            return existing
        raise AuthError(
            "provider_already_linked",
            (
                f"That {provider.title()} account is already connected to a different "
                f"Helios account."
            ),
            status=409,
        )

    already = [a for a in user.oauth_accounts if a.provider == provider]
    if already:
        raise AuthError(
            "provider_conflict",
            (
                f"Your account already has a {provider.title()} connection. Disconnect it "
                f"first if you want to connect a different {provider.title()} account."
            ),
            status=409,
        )

    account = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_account_id=str(provider_account_id),
        provider_email=normalise_email(email or "") or None,
        provider_username=username,
    )
    session.add(account)
    session.flush()
    session.refresh(user)
    logger.info("Linked %s to account %s", provider, user.id)
    return account


def authentication_method_count(user: User) -> int:
    """How many distinct ways this person can prove who they are."""
    return (1 if user.has_password else 0) + len(user.oauth_accounts)


def unlink_provider(session: Session, user: User, provider: str) -> None:
    """Disconnect a provider, unless it is the only way in.

    The check is the whole reason this is not a two-line delete. Somebody who signed up
    with Google, never set a password, and disconnects Google has just locked themselves
    out of an account they cannot even use password reset on — there is no password to
    reset to.
    """
    account = next((a for a in user.oauth_accounts if a.provider == provider), None)
    if account is None:
        raise AuthError(
            "provider_not_linked",
            f"Your account is not connected to {provider.title()}.",
            status=404,
        )

    if authentication_method_count(user) <= 1:
        raise AuthError(
            "last_auth_method",
            (
                f"{provider.title()} is currently the only way to sign in to this account. "
                f"Set a password first, then you can disconnect it."
            ),
            status=409,
        )

    session.delete(account)
    session.flush()
    session.refresh(user)
    logger.info("Unlinked %s from account %s", provider, user.id)


def count_users(session: Session) -> int:
    return int(session.execute(select(func.count()).select_from(User)).scalar_one())
