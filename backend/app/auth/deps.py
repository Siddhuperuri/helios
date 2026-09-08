"""How a request gets a user.

Three dependencies, and choosing between them is a product decision rather than a
technical one:

``optional_user``
    Returns a user or ``None``. This is what the estimate routes use, and it is what keeps
    the calculator open to people without accounts. A signed-in visitor's estimate gets an
    owner; a signed-out visitor's does not; neither is turned away.

``current_user``
    Requires a valid access token. The dashboard and account settings use it.

``verified_user``
    Additionally requires a confirmed address. Nothing uses it yet, deliberately — see
    :func:`verified_user` for what it is reserved for.

Client identity for rate limiting is also here, because it has the same problem: working
out who is making a request when there are proxies in front of you.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import service
from app.config import get_settings
from app.db.base import get_session
from app.db.models import User
from app.security import tokens

logger = logging.getLogger(__name__)


def bearer_token(request: Request) -> str | None:
    """The access token from the Authorization header, if there is one."""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


def optional_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    """The signed-in user, or ``None``.

    An invalid or expired token is treated as "not signed in" rather than as an error.
    That is the right behaviour for a route that works either way: somebody whose access
    token expired mid-session should get the anonymous experience and a 401 from the next
    authenticated call, not a hard failure on the calculator.
    """
    token = bearer_token(request)
    if not token:
        return None
    try:
        claims = tokens.decode_access_token(token)
    except tokens.TokenError:
        return None

    user = service.get_user(session, claims.user_id)
    if user is None or not user.is_active:
        return None
    return user


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """The signed-in user. 401 if there is not one.

    The ``error`` field is what the frontend's client switches on: ``token_expired`` tells
    it to attempt a silent refresh and retry, anything else tells it to clear its session
    and stop. Without that distinction the client either never refreshes or refreshes in a
    loop.
    """
    token = bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "not_authenticated",
                "message": "Sign in to continue.",
                "remedy": "Sign in and try again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = tokens.decode_access_token(token)
    except tokens.TokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "error": exc.code,
                "message": exc.message,
                "remedy": "Sign in again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = service.get_user(session, claims.user_id)
    if user is None:
        # A valid signature for an account that no longer exists. The token is not
        # forgeable, so this is a deleted account, not an attack.
        raise HTTPException(
            status_code=401,
            detail={
                "error": "account_missing",
                "message": "That account no longer exists.",
                "remedy": "Sign in with a different account.",
            },
        )
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "account_disabled",
                "message": "That account has been deactivated.",
                "remedy": "Contact support if you think this is wrong.",
            },
        )
    return user


def verified_user(user: User = Depends(current_user)) -> User:
    """A user with a confirmed email address.

    Nothing in the product requires this yet, and that is a deliberate product position
    rather than an oversight: an unverified account can use the calculator, run
    predictions, save estimates, edit assumptions and use the analysis console. Blocking
    any of that would trade a real loss of usefulness for no security gain, since none of
    it can harm anyone else.

    It is here for the actions that *would*: sending a report to a third party, making an
    estimate visible beyond its link, inviting a collaborator. When those exist, they use
    this.
    """
    if not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "email_not_verified",
                "message": "Confirm your email address before doing this.",
                "remedy": "Check your inbox for the confirmation link, or request a new one.",
            },
        )
    return user


# --------------------------------------------------------------------------------------
# Client identity
# --------------------------------------------------------------------------------------

def client_ip(request: Request) -> str:
    """The client's address, read correctly through the proxies we actually have.

    ``X-Forwarded-For`` is a list that each hop appends to, and a client can send one to
    begin with. Taking the leftmost entry — which is the common mistake — lets anybody
    choose their own rate-limit identity by sending a header. The trustworthy entry is
    counted from the right: with N proxies of ours in front, the address our first proxy
    saw is N entries from the end.

    ``SOLAR_TRUSTED_PROXY_HOPS`` defaults to 0, so a directly exposed backend ignores the
    header entirely. The shipped Nginx topology sets it to 1.
    """
    hops = get_settings().server.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            chain = [part.strip() for part in forwarded.split(",") if part.strip()]
            if chain:
                index = max(0, len(chain) - hops)
                return chain[index] if index < len(chain) else chain[-1]
    return request.client.host if request.client else "unknown"


def rate_limit_identity(request: Request) -> str:
    """Who a request is counted against.

    A signed-in user is counted as themselves, so that everybody behind one office NAT does
    not share a budget. Everyone else is counted by address. The user id is taken from the
    token's signature alone — no database read — because this runs on every request.
    """
    token = bearer_token(request)
    if token:
        try:
            return f"user:{tokens.decode_access_token(token).user_id}"
        except tokens.TokenError:
            pass
    return f"ip:{client_ip(request)}"
